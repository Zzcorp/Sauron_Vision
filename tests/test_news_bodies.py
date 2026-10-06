"""The article body, which nothing in this platform had ever fetched.

`NewsArticle.raw_content` is called "the full scraped body" across the
codebase, and `cleanup_news_bodies` exists only to blank it after 90 days
because it "is nearly all of [news's] weight". No scraper ever wrote a
character into it. Every other reference in the tree was a READ or that strip:
a retention policy for a field nobody filled.

The consequence was not a blank panel. `ai_agents/tasks.py` computes sentiment
from `content_summary or raw_content[:2000]`, and `content_summary` was the RSS
`summary`/`description` capped at 1000 chars — frequently empty, usually a
teaser. So the sentiment score, the urgency label, the affected-instrument
match and the brain's news context were, in the common case, measured off a
headline and presented as a reading of an article.

No test here touches the network. `extract_main_text` is deliberately
network-free because it is the half that breaks, and the fetch path is
exercised against a fake session.

Run with:  python manage.py test tests.test_news_bodies
"""
import socket
from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone


def _para(n=1, words=30):
    """A paragraph long enough to read as prose rather than as chrome."""
    return " ".join(f"sentence{n}word{i}" for i in range(words)) + "."


def _page(body_html):
    return f"<html><head><title>t</title></head><body>{body_html}</body></html>"


class _Resp:
    """The bits of a requests Response that fetch_article_body touches."""

    def __init__(self, *, status=200, ctype="text/html; charset=utf-8",
                 body="", encoding="utf-8", headers=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self.encoding = encoding
        self._body = body.encode("utf-8") if isinstance(body, str) else body
        self.closed = False

    def iter_content(self, chunk_size=65536, decode_unicode=False):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i:i + chunk_size]

    def close(self):
        self.closed = True


class _Session:
    def __init__(self, resp):
        """`resp` is one response for every URL, an exception to raise, or a
        {url: response} map for a fetch that touches more than one URL."""
        self._resp = resp
        self.calls = []

    def get(self, url, **kw):
        self.calls.append((url, kw))
        resp = self._resp.get(url) if isinstance(self._resp, dict) else self._resp
        if isinstance(resp, Exception):
            raise resp
        if resp is None:
            raise AssertionError(f"unexpected GET {url}")
        return resp


#: A public address, for the resolver double: the fetch refuses a host that
#: resolves into the private ranges, so every test that expects a request
#: has to answer the resolver with something on the internet.
_PUBLIC = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def _resolver(**by_host):
    """A socket.getaddrinfo double: {host: ip}; anything else is public."""
    def getaddrinfo(host, *a, **kw):
        ip = by_host.get(host)
        if ip is None:
            return list(_PUBLIC)
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 0))]
    return getaddrinfo


class ExtractionTests(SimpleTestCase):
    """Pure text-from-HTML. No network, no database, no Django."""

    def test_it_prefers_the_article_element(self):
        from scraping.article_body import extract_main_text
        html = _page(
            f"<nav><p>{_para(9)}</p></nav>"
            f"<article><p>{_para(1)}</p><p>{_para(2)}</p></article>")
        text = extract_main_text(html)
        self.assertIn("sentence1word0", text)
        self.assertIn("sentence2word0", text)
        self.assertNotIn("sentence9word0", text)

    def test_it_strips_the_site_chrome(self):
        from scraping.article_body import extract_main_text
        html = _page(
            f"<header><p>{_para(7)}</p></header>"
            f"<article><p>{_para(1)}</p><p>{_para(2)}</p></article>"
            f"<aside><p>{_para(8)}</p></aside>"
            f"<footer><p>{_para(6)}</p></footer>"
            f"<form><p>{_para(5)}</p></form>"
            f"<script>var x = '{_para(4)}';</script>")
        text = extract_main_text(html)
        for n in (4, 5, 6, 7, 8):
            self.assertNotIn(f"sentence{n}word0", text)

    def test_short_paragraphs_are_captions_not_prose(self):
        from scraping.article_body import extract_main_text
        html = _page(f"<article><p>Photo: Reuters</p><p>By A Reporter</p>"
                     f"<p>{_para(1)}</p><p>{_para(2)}</p></article>")
        text = extract_main_text(html)
        self.assertNotIn("Photo: Reuters", text)
        self.assertNotIn("By A Reporter", text)
        self.assertIn("sentence1word0", text)

    def test_without_an_article_tag_the_densest_block_wins(self):
        """Most news pages have no <article>. "All the <p> on the page" would
        concatenate the story with three sidebars of teasers."""
        from scraping.article_body import extract_main_text
        html = _page(
            f"<div id='teasers'><p>{_para(9)}</p></div>"
            f"<div id='story'><p>{_para(1)}</p><p>{_para(2)}</p>"
            f"<p>{_para(3)}</p></div>")
        text = extract_main_text(html)
        self.assertIn("sentence1word0", text)
        self.assertIn("sentence3word0", text)

    def test_the_text_is_capped(self):
        from scraping.article_body import MAX_TEXT_CHARS, extract_main_text
        html = _page("<article>" + "".join(
            f"<p>{_para(i, words=60)}</p>" for i in range(400)) + "</article>")
        self.assertLessEqual(len(extract_main_text(html)), MAX_TEXT_CHARS)

    def test_garbage_in_returns_empty_not_an_exception(self):
        from scraping.article_body import extract_main_text
        for junk in ("", "<<<", "not html at all", "\x00\x01"):
            self.assertIsInstance(extract_main_text(junk), str)


class FetchGuardTests(SimpleTestCase):

    def _fetch(self, resp, *, allowed=True, url="https://example.com/a"):
        from scraping import article_body
        with patch.object(article_body, "_robots_allows", return_value=allowed), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            return article_body.fetch_article_body(url, session=_Session(resp))

    def test_robots_is_asked_before_the_page(self):
        text, reason = self._fetch(_Resp(body=_page("<article><p>x</p></article>")),
                                   allowed=False)
        self.assertEqual(text, "")
        self.assertEqual(reason, "robots")

    def test_a_good_page_yields_its_prose(self):
        body = _page(f"<article><p>{_para(1)}</p><p>{_para(2)}</p>"
                     f"<p>{_para(3)}</p></article>")
        text, reason = self._fetch(_Resp(body=body))
        self.assertEqual(reason, "ok")
        self.assertIn("sentence1word0", text)

    def test_a_paywall_stub_is_not_stored(self):
        """Below the floor we return "". Storing it would make raw_content
        non-empty, and every reader in the tree — including the retention
        task — treats non-empty as "we have the article"."""
        text, reason = self._fetch(
            _Resp(body=_page("<article><p>Subscribe to continue reading this "
                             "article and get unlimited access.</p></article>")))
        self.assertEqual(text, "")
        self.assertIn("too short", reason)

    def test_a_non_200_is_refused(self):
        text, reason = self._fetch(_Resp(status=404))
        self.assertEqual(text, "")
        self.assertIn("404", reason)

    def test_a_pdf_is_refused_rather_than_parsed_as_html(self):
        """Feeding a PDF to an HTML parser produces plausible nonsense rather
        than an error, which is the worst of both."""
        text, reason = self._fetch(_Resp(ctype="application/pdf", body="%PDF-1.4"))
        self.assertEqual(text, "")
        self.assertIn("content-type", reason)

    def test_a_dead_host_is_data_not_a_crash(self):
        text, reason = self._fetch(RuntimeError("connection reset"))
        self.assertEqual(text, "")
        self.assertIn("fetch failed", reason)

    def test_it_identifies_itself(self):
        from scraping import article_body
        session = _Session(_Resp(body=_page("<article><p>x</p></article>")))
        with patch.object(article_body, "_robots_allows", return_value=True):
            article_body.fetch_article_body("https://example.com/a",
                                            session=session)
        _url, kw = session.calls[0]
        self.assertIn("SauronVision", kw["headers"]["User-Agent"])
        self.assertTrue(kw.get("timeout"))

    def test_an_empty_url_is_refused_without_a_request(self):
        from scraping import article_body
        session = _Session(_Resp())
        text, reason = article_body.fetch_article_body("", session=session)
        self.assertEqual(text, "")
        self.assertEqual(session.calls, [])


def _robots(session, url):
    """_robots_allows against a fresh per-process cache."""
    from scraping import article_body
    with patch.dict(article_body._robots, clear=True), \
            patch("socket.getaddrinfo", side_effect=_resolver()):
        return article_body._robots_allows(url, session=session)


class OneHostCannotHoldTheWorkerTests(SimpleTestCase):
    """Review 2026-09-28: robots.txt was read by `RobotFileParser.read()`,
    which is `urllib.request.urlopen(url)` with NO timeout, and the page
    read was bounded per socket operation only — a host that accepted the
    connection and never answered, or dripped a byte every ten seconds,
    held one of worker-slow's two slots (shared with the ai queue) until
    the container was restarted. One deadline now covers the whole fetch."""

    def test_robots_is_read_through_the_session_with_a_timeout(self):
        session = _Session(_Resp(ctype="text/plain",
                                 body="User-agent: *\nDisallow: /private/\n"))
        self.assertTrue(_robots(session, "https://example.com/a"))
        url, kw = session.calls[0]
        self.assertEqual(url, "https://example.com/robots.txt")
        self.assertTrue(kw.get("timeout"))
        self.assertIn("SauronVision", kw["headers"]["User-Agent"])
        self.assertFalse(_robots(session, "https://example.com/private/x"))

    def test_a_forbidden_robots_refuses_and_a_missing_one_allows(self):
        """RobotFileParser.read()'s own table, kept: 401/403 disallow all,
        any other 4xx allows all."""
        self.assertFalse(_robots(_Session(_Resp(status=403, ctype="text/plain")),
                                 "https://shut.example.com/a"))
        self.assertTrue(_robots(_Session(_Resp(status=404, ctype="text/plain")),
                                "https://open.example.com/a"))

    def test_an_unreachable_robots_still_allows(self):
        """The docstring's promise: an unreadable file is not an outage."""
        self.assertTrue(_robots(_Session(RuntimeError("timed out")),
                                "https://dead.example.com/a"))

    def test_the_whole_fetch_has_one_wall_clock_deadline(self):
        """A host that drips bytes resets a per-read timeout on every chunk.
        The budget is on the clock, not on the socket."""
        from scraping import article_body
        clock = {"t": 1000.0}
        body = _page("<article>" + "".join(
            f"<p>{_para(i, words=60)}</p>" for i in range(400)) + "</article>")

        class _Trickle(_Resp):
            def iter_content(self, chunk_size=65536, decode_unicode=False):
                for chunk in super().iter_content(chunk_size, decode_unicode):
                    # 20s between chunks — each one inside the socket
                    # timeout, all of them together far past the budget.
                    clock["t"] += 20.0
                    yield chunk

        self.assertGreater(len(body), 3 * 65536)
        with patch.object(article_body.time, "monotonic",
                          side_effect=lambda: clock["t"]):
            text, reason = FetchGuardTests._fetch(self, _Trickle(body=body))
        self.assertEqual(text, "")
        self.assertIn("deadline", reason)

    def test_the_socket_timeout_is_bounded_by_the_remaining_budget(self):
        from scraping import article_body
        session = _Session(_Resp(body=_page("<article><p>x</p></article>")))
        with patch.object(article_body, "_robots_allows", return_value=True), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            article_body.fetch_article_body("https://example.com/a",
                                            session=session)
        _url, kw = session.calls[0]
        self.assertLessEqual(kw["timeout"], article_body.FETCH_DEADLINE_S)
        self.assertLessEqual(kw["timeout"], article_body.FETCH_TIMEOUT_S)


class TheBytesAreDecodedAsThePageSaysTests(SimpleTestCase):
    """Review 2026-09-28: requests sets `Response.encoding` to ISO-8859-1 for
    any text/* Content-Type without a charset parameter, and the fetch took
    that word for it. A UTF-8 page that declares its charset only in <meta>
    — common — was decoded as Latin-1 and 'Société Générale' was stored as
    'SociÃ©tÃ© GÃ©nÃ©rale' in raw_content, the article page and the
    analyst's reading."""

    _FRENCH = ("Société Générale a annoncé ses résultats trimestriels — "
               "« très solides », selon l’équipe dirigeante, qui évoque une "
               "croissance à deux chiffres et un bénéfice net en hausse.")

    def _french_page(self, head=""):
        return ("<html><head>" + head + "<title>t</title></head><body><article>"
                + "".join(f"<p>{self._FRENCH} ({i})</p>" for i in range(6))
                + "</article></body></html>").encode("utf-8")

    def test_a_meta_charset_beats_requests_latin1_default(self):
        text, reason = FetchGuardTests._fetch(self, _Resp(
            ctype="text/html", encoding="ISO-8859-1",
            body=self._french_page('<meta charset="utf-8">')))
        self.assertEqual(reason, "ok")
        self.assertIn("Société Générale", text)
        self.assertNotIn("Ã", text)

    def test_without_any_charset_the_bytes_are_sniffed(self):
        text, reason = FetchGuardTests._fetch(self, _Resp(
            ctype="text/html", encoding="ISO-8859-1", body=self._french_page()))
        self.assertEqual(reason, "ok")
        self.assertIn("Société Générale", text)
        self.assertNotIn("Ã", text)

    def test_a_charset_the_header_states_is_believed(self):
        body = ("<html><body><article>" + "".join(
            f"<p>Sociedad Española de Electromedicina — resultados {i} "
            f"{_para(i)}</p>" for i in range(6)) + "</article></body></html>"
                ).encode("iso-8859-1", "replace")
        text, reason = FetchGuardTests._fetch(self, _Resp(
            ctype="text/html; charset=iso-8859-1", encoding="ISO-8859-1",
            body=body))
        self.assertEqual(reason, "ok")
        self.assertIn("Española", text)


class TheFetchStaysOnTheInternetTests(SimpleTestCase):
    """Review 2026-09-28: the fetch followed redirects with requests' default
    and checked nothing but the scheme, so a feed link that answered 30x
    into the compose network (web:8000, the metadata address) was fetched
    from inside worker-slow, and robots.txt had been asked for the original
    host only. A host is resolved and refused when it lands in a private,
    loopback or link-local range; a redirect is one hop of a new fetch, with
    the same guards and its own robots answer."""

    def _prose(self):
        return _page(f"<article><p>{_para(1)}</p><p>{_para(2)}</p>"
                     f"<p>{_para(3)}</p></article>")

    def test_a_host_on_a_private_range_is_never_requested(self):
        from scraping import article_body
        session = _Session(_Resp(body=self._prose()))
        with patch.object(article_body, "_robots_allows") as robots, \
                patch("socket.getaddrinfo",
                      side_effect=_resolver(**{"metadata.example.com":
                                               "169.254.169.254"})):
            text, reason = article_body.fetch_article_body(
                "https://metadata.example.com/a", session=session)
        self.assertEqual(text, "")
        self.assertIn("private", reason)
        self.assertEqual(session.calls, [])
        # robots.txt is a GET to the same host: not asked either.
        robots.assert_not_called()

    def test_loopback_and_the_compose_network_are_private(self):
        from scraping import article_body
        for host, ip in (("localhost", "127.0.0.1"), ("web", "172.18.0.3"),
                         ("box", "10.0.0.5"), ("six", "::1")):
            session = _Session(_Resp(body=self._prose()))
            with patch.object(article_body, "_robots_allows", return_value=True), \
                    patch("socket.getaddrinfo", side_effect=_resolver(**{host: ip})):
                text, reason = article_body.fetch_article_body(
                    f"http://{host}:8000/a", session=session)
            self.assertEqual((text, session.calls), ("", []), host)
            self.assertIn("private", reason, host)

    def test_a_redirect_is_one_hop_with_its_own_robots_answer(self):
        from scraping import article_body
        first = "https://feed.example.com/go/1"
        final = "https://paper.example.com/story"
        session = _Session({
            first: _Resp(status=302, headers={"Location": final}),
            final: _Resp(body=self._prose())})
        asked = []

        def robots(url, **kw):
            asked.append(url)
            return True

        with patch.object(article_body, "_robots_allows", side_effect=robots), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            text, reason = article_body.fetch_article_body(first, session=session)
        self.assertEqual(reason, "ok")
        self.assertIn("sentence1word0", text)
        # requests must not follow on its own: every hop is ours to check.
        for _url, kw in session.calls:
            self.assertIs(kw.get("allow_redirects"), False)
        self.assertEqual(asked, [first, final])

    def test_a_relative_location_is_resolved_against_the_hop(self):
        from scraping import article_body
        first = "https://paper.example.com/amp/story"
        session = _Session({
            first: _Resp(status=301, headers={"Location": "/story"}),
            "https://paper.example.com/story": _Resp(body=self._prose())})
        with patch.object(article_body, "_robots_allows", return_value=True), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            text, reason = article_body.fetch_article_body(first, session=session)
        self.assertEqual(reason, "ok")

    def test_a_redirect_into_the_private_network_is_refused(self):
        from scraping import article_body
        first = "https://feed.example.com/go/2"
        session = _Session({
            first: _Resp(status=302, headers={"Location": "http://web:8000/x"}),
            "http://web:8000/x": _Resp(body=self._prose())})
        with patch.object(article_body, "_robots_allows", return_value=True), \
                patch("socket.getaddrinfo", side_effect=_resolver(web="172.18.0.3")):
            text, reason = article_body.fetch_article_body(first, session=session)
        self.assertEqual(text, "")
        self.assertIn("private", reason)
        self.assertEqual([u for u, _ in session.calls], [first])

    def test_a_redirect_the_new_hosts_robots_refuses_is_not_fetched(self):
        from scraping import article_body
        first = "https://feed.example.com/go/3"
        final = "https://shut.example.com/story"
        session = _Session({
            first: _Resp(status=302, headers={"Location": final}),
            final: _Resp(body=self._prose())})
        with patch.object(article_body, "_robots_allows",
                          side_effect=lambda url, **kw: "shut." not in url), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            text, reason = article_body.fetch_article_body(first, session=session)
        self.assertEqual((text, reason), ("", "robots"))
        self.assertEqual([u for u, _ in session.calls], [first])

    def test_a_redirect_loop_ends(self):
        from scraping import article_body
        a, b = "https://a.example.com/1", "https://b.example.com/1"
        session = _Session({a: _Resp(status=302, headers={"Location": b}),
                            b: _Resp(status=302, headers={"Location": a})})
        with patch.object(article_body, "_robots_allows", return_value=True), \
                patch("socket.getaddrinfo", side_effect=_resolver()):
            text, reason = article_body.fetch_article_body(a, session=session)
        self.assertEqual(text, "")
        self.assertIn("redirect", reason)
        self.assertLessEqual(len(session.calls), article_body.MAX_REDIRECTS + 1)


def _article(url="https://example.com/1", *, age_hours=1.0, raw="",
             summary="s", title="T"):
    from scraping.models import NewsArticle
    return NewsArticle.objects.create(
        url=url, title=title, source="Test",
        published_at=timezone.now() - timedelta(hours=age_hours),
        content_summary=summary, raw_content=raw)


class TheTaskFillsTheFieldNobodyFilledTests(TestCase):

    def setUp(self):
        # The task is gated on `scraper_news`, deliberately: a component of
        # its own would be created is_enabled=False and the task would
        # silently never run. The flip side is that these tests must arm the
        # switch, and the first run of this file proved it — every one of them
        # got the guard's skip dict instead of a result.
        # BOTH switches: guarded_task checks platform_master before the
        # component, so arming only the component leaves every call returning
        # {"status": "skipped", "reason": "platform_disabled"}.
        from core.platform_control import PlatformComponent
        for key, name, cat in (
                ("platform_master", "Platform Master Switch", "system"),
                ("scraper_news", "Breaking News", "scraper")):
            PlatformComponent.objects.update_or_create(
                key=key,
                defaults={"name": name, "category": cat, "is_enabled": True})
        # The refusal memory (scraping.tasks.BODY_REFUSED_KEY) lives in the
        # cache, which outlives a test's transaction while the row ids are
        # reused: a row refused in one test must not be remembered in the
        # next.
        from django.core.cache import cache
        cache.clear()

    def _run(self, **kw):
        from scraping.tasks import fetch_news_bodies
        return fetch_news_bodies(**kw)

    def test_the_guard_is_what_stops_it_when_news_is_off(self):
        """Pin the gating choice itself: with the switch off the task must
        no-op rather than reach the network."""
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.filter(key="scraper_news").update(
            is_enabled=False)
        _article()
        with patch("scraping.article_body.fetch_article_body") as f:
            out = self._run()
        f.assert_not_called()
        self.assertNotIn("filled", out)

    def test_it_writes_raw_content(self):
        from scraping.models import NewsArticle
        art = _article()
        with patch("scraping.article_body.fetch_article_body",
                   return_value=("the body text", "ok")):
            out = self._run()
        self.assertEqual(out["filled"], 1)
        self.assertEqual(NewsArticle.objects.get(pk=art.pk).raw_content,
                         "the body text")

    def test_it_does_NOT_touch_content_summary(self):
        """The retention task blanks raw_content only on rows that still carry
        a summary. Overwriting the summary with our extraction would eventually
        leave the row with neither."""
        from scraping.models import NewsArticle
        art = _article(summary="the feed's own words")
        with patch("scraping.article_body.fetch_article_body",
                   return_value=("the body text", "ok")):
            self._run()
        self.assertEqual(NewsArticle.objects.get(pk=art.pk).content_summary,
                         "the feed's own words")

    def test_a_row_that_already_has_a_body_is_not_refetched(self):
        art = _article(raw="already here")
        with patch("scraping.article_body.fetch_article_body") as f:
            out = self._run()
        f.assert_not_called()
        self.assertEqual(out["considered"], 0)
        del art

    def test_stories_older_than_the_window_are_not_retried_forever(self):
        """The age window replaces a retry counter. A paywalled article ages
        out of the queryset by itself — no new column, no migration, and no
        URL hammered until the end of time."""
        from scraping.tasks import BODY_FETCH_MAX_AGE_HOURS
        _article(url="https://example.com/old",
                 age_hours=BODY_FETCH_MAX_AGE_HOURS + 5)
        with patch("scraping.article_body.fetch_article_body") as f:
            out = self._run()
        f.assert_not_called()
        self.assertEqual(out["considered"], 0)

    def test_newest_first(self):
        """If the batch cannot keep up, the stories the platform is about to
        reason about are the ones that get bodies."""
        _article(url="https://example.com/old", age_hours=40)
        _article(url="https://example.com/new", age_hours=1)
        seen = []

        def fake(url, **kw):
            seen.append(url)
            return "", "too short"

        with patch("scraping.article_body.fetch_article_body", side_effect=fake):
            self._run(limit=1)
        self.assertEqual(seen, ["https://example.com/new"])

    def test_a_refusal_leaves_the_row_empty_and_is_counted(self):
        from scraping.models import NewsArticle
        art = _article()
        with patch("scraping.article_body.fetch_article_body",
                   return_value=("", "robots")):
            out = self._run()
        self.assertEqual(out["filled"], 0)
        self.assertEqual(out["reasons"].get("robots"), 1)
        self.assertEqual(NewsArticle.objects.get(pk=art.pk).raw_content, "")

    def test_one_raising_host_does_not_fail_the_run(self):
        from scraping.models import NewsArticle
        bad = _article(url="https://bad.example.com/1", age_hours=1)
        good = _article(url="https://good.example.com/2", age_hours=2)

        def fake(url, **kw):
            if "bad" in url:
                raise RuntimeError("boom")
            return "body", "ok"

        with patch("scraping.article_body.fetch_article_body", side_effect=fake):
            out = self._run()
        self.assertEqual(out["filled"], 1)
        self.assertEqual(NewsArticle.objects.get(pk=good.pk).raw_content, "body")
        self.assertEqual(NewsArticle.objects.get(pk=bad.pk).raw_content, "")

    def test_the_batch_is_bounded(self):
        for i in range(6):
            _article(url=f"https://example.com/{i}", age_hours=1)
        with patch("scraping.article_body.fetch_article_body",
                   return_value=("body", "ok")):
            out = self._run(limit=3)
        self.assertEqual(out["considered"], 3)


class TheSharedRowKeepsTheFeedsVerdictTests(TestCase):
    """Review 2026-09-28. fetch_news_bodies writes the scraper_news row the
    feed task writes, every 10 minutes to the feed's 15, and it returned
    keys the gate could not read (`considered`, `filled`), so judge_result
    graded every run 'success' — a run that considered 25 and filled 0, and
    a run with nothing to do — and mark_run wrote that over the feed's real
    verdict within ten minutes of it landing. A dead RSS host showed green.
    This is the shared-row overwrite core.task_gate's own docstring
    describes, and `idle` is the convention it gives a second writer."""

    def setUp(self):
        from core.platform_control import PlatformComponent
        PlatformComponent.objects.update_or_create(
            key="platform_master",
            defaults={"name": "Platform Master Switch", "category": "system",
                      "is_enabled": True})
        self.then = timezone.now() - timedelta(minutes=4)
        PlatformComponent.objects.update_or_create(
            key="scraper_news",
            defaults={"name": "Breaking News", "category": "scraper",
                      "is_enabled": True, "last_status": "error",
                      "last_message": "rss: feed.example.com answered 503",
                      "last_run_at": self.then, "run_count": 9,
                      "error_count": 1})
        from django.core.cache import cache
        cache.clear()

    def _row(self):
        from core.platform_control import PlatformComponent
        return PlatformComponent.objects.get(key="scraper_news")

    def _run(self, **kw):
        from scraping.tasks import fetch_news_bodies
        return fetch_news_bodies(**kw)

    def test_nothing_due_leaves_the_feeds_error_on_the_row(self):
        with patch("scraping.article_body.fetch_article_body") as f:
            out = self._run()
        f.assert_not_called()
        self.assertTrue(out.get("idle"))
        row = self._row()
        self.assertEqual((row.last_status, row.last_message, row.last_run_at,
                          row.run_count),
                         ("error", "rss: feed.example.com answered 503",
                          self.then, 9))

    def test_a_batch_the_publishers_refused_leaves_the_feeds_verdict_too(self):
        """2026-10-06: a batch that filled nothing used to write "handled 2
        rows and stored none" over the feed's verdict — and the digest read
        it under BREAKING NEWS as the news having stopped. A publisher's no
        changes nothing about the news: the pass says so in its own words
        and the row keeps the feed's error (tests/test_health_hygiene.py
        has the rest: the road's failures are a warning in words)."""
        _article(url="https://example.com/1")
        _article(url="https://example.com/2")
        with patch("scraping.article_body.fetch_article_body",
                   return_value=("", "too short (12 chars) — paywall or wall")):
            out = self._run()
        self.assertIn("2 article bodies tried, none kept", out.get("idle", ""))
        self.assertNotIn("attempted", out)
        row = self._row()
        self.assertEqual((row.last_status, row.last_message),
                         ("error", "rss: feed.example.com answered 503"))

    def test_a_batch_is_graded_on_what_it_stored(self):
        _article(url="https://example.com/1")
        _article(url="https://example.com/2")

        def fake(url, **kw):
            return ("body", "ok") if url.endswith("/1") else ("", "robots")

        with patch("scraping.article_body.fetch_article_body", side_effect=fake):
            out = self._run()
        self.assertEqual((out["considered"], out["filled"]), (2, 1))
        row = self._row()
        self.assertEqual(row.last_status, "success")
        self.assertEqual(row.last_message, "handled 2, stored 1")


class TheFeedSummaryIsBackfilledTests(TestCase):
    """`get_or_create(url=..., defaults={...})` applies defaults ONLY on
    creation. A row first stored from a pass whose <description> was empty kept
    an empty summary forever, even when the next pass of the same feed carried
    one — and that empty string is what the sentiment pass reads first."""

    def _one_feed(self, entry):
        """Run fetch_rss_news over exactly one synthetic feed."""
        from scraping.scrapers import news_aggregator

        class _Feed:
            entries = [entry]
            bozo = 0

        with patch.object(news_aggregator, "RSS_FEEDS",
                          {"test_wire": "https://feed.example.com/rss"}):
            with patch.object(news_aggregator.feedparser, "parse",
                              return_value=_Feed()):
                return news_aggregator.fetch_rss_news(max_per_feed=5)

    def test_an_empty_summary_is_filled_on_a_later_pass(self):
        from scraping.models import NewsArticle

        art = _article(url="https://example.com/wire", summary="")
        self._one_feed({"title": "T", "link": "https://example.com/wire",
                        "summary": "the description that arrived late"})
        self.assertEqual(
            NewsArticle.objects.get(pk=art.pk).content_summary,
            "the description that arrived late")

    def test_a_first_pass_still_stores_the_summary_it_has(self):
        """The backfill must not have displaced the creation path."""
        from scraping.models import NewsArticle

        self._one_feed({"title": "Fresh", "link": "https://example.com/fresh",
                        "summary": "first words"})
        row = NewsArticle.objects.get(url="https://example.com/fresh")
        self.assertEqual(row.content_summary, "first words")

    def test_a_row_that_already_has_words_keeps_them(self):
        from scraping.models import NewsArticle

        art = _article(url="https://example.com/kept", summary="first words")
        self._one_feed({"title": "T", "link": "https://example.com/kept",
                        "summary": "second words"})
        self.assertEqual(NewsArticle.objects.get(pk=art.pk).content_summary,
                         "first words")

    def test_an_existing_summary_is_not_overwritten(self):
        """Only the empty case is backfilled. The feed's first words are as
        good as its later ones, and rewriting them on every pass would churn
        the table for nothing."""
        import inspect

        from scraping.scrapers import news_aggregator
        src = inspect.getsource(news_aggregator)
        self.assertIn("not article.content_summary", src)
        self.assertIn("not row.content_summary", src)


class TheRetentionPairStaysValidTests(SimpleTestCase):
    """cleanup_news_bodies blanks raw_content only where content_summary is
    non-empty, so the row keeps something readable. The new writer must not
    break that invariant by filling one and clearing the other."""

    def test_the_cleanup_still_requires_a_summary_before_stripping(self):
        import inspect

        from market_data import cleanup_tasks
        src = inspect.getsource(cleanup_tasks.cleanup_news_bodies)
        self.assertIn('exclude(content_summary="")', src)
        self.assertIn("raw_content=\"\"", src)

    def test_the_body_task_writes_only_raw_content(self):
        import inspect

        from scraping import tasks
        src = inspect.getsource(tasks.fetch_news_bodies)
        self.assertIn("update(raw_content=text)", src)
        self.assertNotIn("content_summary=", src)
