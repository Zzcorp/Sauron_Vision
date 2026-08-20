"""The icons the platform declares must be icons the platform has.

Two failures this pins, both of which were live:

  1. `manifest.json` declared `/static/logo/sauron_192.png` and
     `sauron_512.png`. Neither file existed. A manifest icon that 404s does
     not raise anything — the browser just declines to install the PWA and
     says nothing, so it shipped that way indefinitely.

  2. `og:image` and `twitter:image` were rendered with `{% static %}`, which
     produces "/static/logo/...". Every scraper — Facebook, LinkedIn, Slack,
     X, iMessage — requires an absolute URL there and silently drops a
     relative one. Every link ever shared to this platform previewed with no
     image. It fails on somebody else's server, which is why nobody saw it.

Neither needs a browser, so all of this runs in CI. Rasterizing is the part
that needs Chrome, and that is `manage.py build_icons`, run by hand; the
PNGs it produces are committed and these tests check the committed files.

Run with:  python manage.py test tests.test_brand_assets
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

LOGO = Path(settings.BASE_DIR) / "static" / "logo"

# name -> the square size it must be, from the declaration that names it.
EXPECTED_PNG = {
    "favicon-16.png": 16,
    "favicon-32.png": 32,
    "apple-touch-icon.png": 180,
    "sauron_192.png": 192,
    "sauron_512.png": 512,
}

# Every template that carries its own <head> — each one is a page somebody
# can land on or share, so each has to declare the icons for itself.
HEAD_TEMPLATES = (
    "base.html",
    "landing/the_wall.html",
    "registration/login.html",
    "registration/login_pin.html",
    "dashboard/intro.html",
    "dashboard/locked.html",
    "dashboard/_popout.html",
)


def _template(rel):
    for engine in settings.TEMPLATES:
        for d in engine.get("DIRS", []):
            path = Path(d) / rel
            if path.exists():
                return path.read_text(encoding="utf-8")
    raise AssertionError(f"template not found: {rel}")


def _head(rel):
    """Just the <head>. The page BODY may legitimately still show the older
    wordmark image — the hero on the wall, the badge above the login form —
    and swapping those is a separate visual decision. What must be
    consistent is what the browser and the scrapers are handed."""
    body = _template(rel)
    start = body.lower().find("<head")
    end = body.lower().find("</head>")
    if start < 0 or end < 0:
        raise AssertionError(f"{rel} has no <head>")
    return body[start:end]


class VectorSourceTests(TestCase):
    def test_the_square_mark_exists(self):
        self.assertTrue((LOGO / "sauron_eye.svg").exists(),
                        "the canonical vector mark is missing")

    def test_the_share_card_exists(self):
        self.assertTrue((LOGO / "sauron_og.svg").exists())

    def test_the_mark_is_square(self):
        svg = (LOGO / "sauron_eye.svg").read_text(encoding="utf-8")
        self.assertRegex(svg, r'viewBox="0 0 (\d+) \1"',
                         "a non-square favicon source gets letterboxed or "
                         "cropped by whatever renders it")

    def test_the_mark_rasterizes_standalone(self):
        """No filters, no CSS variables, no external references.

        build_icons screenshots this file on a blank page. A `var(--accent)`
        resolves to nothing there and a filter renders differently in every
        rasterizer — either way the committed PNG stops matching the app.
        """
        svg = (LOGO / "sauron_eye.svg").read_text(encoding="utf-8")
        for banned in ("var(--", "<style", "filter=", "url(http", "<image"):
            self.assertNotIn(banned, svg,
                             f"{banned} cannot survive standalone rasterization")

    def test_the_mark_declares_its_namespace(self):
        """Without xmlns it renders as XML text when served as a file."""
        svg = (LOGO / "sauron_eye.svg").read_text(encoding="utf-8")
        self.assertIn('xmlns="http://www.w3.org/2000/svg"', svg)


class RasterTests(TestCase):
    def test_every_declared_png_exists_at_its_declared_size(self):
        from PIL import Image
        for name, size in EXPECTED_PNG.items():
            path = LOGO / name
            self.assertTrue(path.exists(), f"{name} was never generated")
            with Image.open(path) as im:
                self.assertEqual(
                    im.size, (size, size),
                    f"{name} is {im.size}, but it is declared as {size}x{size}")

    def test_the_ico_carries_the_small_sizes(self):
        from PIL import Image
        path = LOGO / "favicon.ico"
        self.assertTrue(path.exists())
        with Image.open(path) as im:
            sizes = {s for s in getattr(im, "ico", None).sizes()} \
                if hasattr(im, "ico") else {im.size}
            self.assertIn((16, 16), sizes)
            self.assertIn((32, 32), sizes)

    def test_the_share_card_is_the_documented_shape(self):
        """1200x630 is what every scraper crops summary_large_image to. A
        square logo in that slot gets grey bars down both sides."""
        from PIL import Image
        path = LOGO / "og-card.png"
        self.assertTrue(path.exists())
        with Image.open(path) as im:
            self.assertEqual(im.size, (1200, 630))

    def test_the_share_card_is_opaque(self):
        """Alpha in a share card gets composited on whatever the client
        picks, and half of them pick white."""
        from PIL import Image
        with Image.open(LOGO / "og-card.png") as im:
            self.assertNotIn("A", im.getbands())


class ManifestTests(TestCase):
    def setUp(self):
        self.manifest = json.loads(
            (Path(settings.BASE_DIR) / "static" / "manifest.json")
            .read_text(encoding="utf-8"))

    def test_every_manifest_icon_exists(self):
        for icon in self.manifest["icons"]:
            rel = icon["src"].replace("/static/", "", 1)
            self.assertTrue((Path(settings.BASE_DIR) / "static" / rel).exists(),
                            f"manifest declares {icon['src']} — no such file")

    def test_every_manifest_icon_is_the_size_it_claims(self):
        """`sizes: "any"` is skipped, not parsed — it is the correct and
        only meaningful value for the SVG entry, which has no fixed size."""
        from PIL import Image
        checked = 0
        for icon in self.manifest["icons"]:
            if "x" not in icon["sizes"]:
                continue
            rel = icon["src"].replace("/static/", "", 1)
            w, h = (int(n) for n in icon["sizes"].split("x"))
            with Image.open(Path(settings.BASE_DIR) / "static" / rel) as im:
                self.assertEqual(im.size, (w, h), icon["src"])
            checked += 1
        self.assertGreater(checked, 0, "no sized manifest icon was checked")

    def test_the_theme_colour_is_this_platform_s(self):
        """It was #c0392b — a red from some other project, painting the
        mobile browser chrome a colour that appears nowhere in the app."""
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css") \
            .read_text(encoding="utf-8")
        self.assertIn(self.manifest["theme_color"].lower(), css.lower(),
                      "the manifest theme colour is not a token in sauron.css")


class HeadDeclarationTests(TestCase):
    def test_no_head_still_points_at_the_replaced_mark(self):
        """logo_SV.png is the wide, non-square eye this replaced — a 16px
        tab squashed it. A head left pointing at it would hand the browser
        a different brand from its siblings."""
        for rel in HEAD_TEMPLATES:
            self.assertNotIn("logo_SV.png", _head(rel),
                             f"{rel} still serves the old mark as its icon")

    def test_every_head_declares_the_vector(self):
        for rel in HEAD_TEMPLATES:
            self.assertIn("logo/sauron_eye.svg", _head(rel), rel)

    def test_every_head_declares_the_ico_for_clients_that_ask_by_name(self):
        """Crawlers request /favicon.ico and never read these tags."""
        for rel in HEAD_TEMPLATES:
            self.assertIn("logo/favicon.ico", _head(rel), rel)

    def test_the_png_icon_is_not_declared_twice_at_one_size(self):
        """base.html carried two identical <link rel=icon> tags, one above
        the <title> and one below it under a "Favicon" comment."""
        for rel in HEAD_TEMPLATES:
            head = _head(rel)
            sizes = re.findall(r'rel="icon"[^>]*type="image/png"[^>]*sizes="([^"]+)"',
                               head)
            self.assertEqual(len(sizes), len(set(sizes)),
                             f"{rel} declares the same PNG size twice")

    def test_the_theme_colour_is_never_the_foreign_red(self):
        """#c0392b came from another project and painted the mobile browser
        chrome a colour that appears nowhere in this platform.

        Asserted on the TAG, not on the head text — the comment explaining
        the fix names the old colour, and matching the whole head made this
        test fail on its own explanation.
        """
        for rel in HEAD_TEMPLATES:
            for colour in re.findall(r'name="theme-color" content="([^"]+)"',
                                     _head(rel)):
                self.assertNotEqual(colour.lower(), "#c0392b", rel)


class ShareUrlTests(TestCase):
    """The half that was silently broken everywhere."""

    def _page(self, url, **kw):
        # follow=True because "/" is the app for an authed user and a
        # redirect to the login gateway for anyone else, and /dashboard/ is
        # a permanent redirect to "/". The wall itself lives at /wall/.
        return self.client.get(url, HTTP_HOST="testserver", follow=True,
                               **kw).content.decode("utf-8", "replace")

    def test_the_share_image_is_absolute_on_the_wall(self):
        body = self._page("/wall/")
        match = re.search(r'property="og:image" content="([^"]+)"', body)
        self.assertIsNotNone(match, "the wall declares no og:image")
        self.assertTrue(match.group(1).startswith("http"),
                        f"og:image is {match.group(1)!r} — scrapers drop a "
                        f"relative URL and the preview ships with no image")
        self.assertIn("og-card.png", match.group(1))

    def test_the_share_image_is_absolute_on_the_app(self):
        user = User.objects.create_user("brand_u", password="x")
        self.client.force_login(user)
        body = self._page("/")
        for prop in (r'property="og:image"', r'name="twitter:image"'):
            match = re.search(prop + r' content="([^"]+)"', body)
            self.assertIsNotNone(match, prop)
            self.assertTrue(match.group(1).startswith("http"), match.group(1))

    def test_the_app_serves_the_vector_icon(self):
        user = User.objects.create_user("brand_u2", password="x")
        self.client.force_login(user)
        self.assertIn("logo/sauron_eye.svg", self._page("/"))

    def test_the_absolute_url_carries_the_real_host(self):
        from django.template import Context, Template
        from django.test import RequestFactory
        # `testserver` rather than the production hostname: get_host()
        # validates against ALLOWED_HOSTS, which is the very thing that stops
        # a spoofed Host header from pointing the share card at another
        # domain — so the tag cannot be tested with a host the settings do
        # not allow, and that is the correct behaviour, not a limitation.
        request = RequestFactory().get("/", HTTP_HOST="testserver")
        rendered = Template(
            "{% load sauron_tags %}{% static_abs 'logo/og-card.png' %}"
        ).render(Context({"request": request}))
        self.assertIn("og-card.png", rendered)
        self.assertTrue(rendered.startswith("http://testserver/"))

    def test_it_degrades_to_a_relative_path_without_a_request(self):
        """A template rendered outside a request still has to produce a
        usable <img> src — inventing a hostname would point somewhere that
        may not exist."""
        from django.template import Context, Template
        rendered = Template(
            "{% load sauron_tags %}{% static_abs 'logo/og-card.png' %}"
        ).render(Context({}))
        self.assertTrue(rendered.endswith("og-card.png"))
        self.assertFalse(rendered.startswith("http"))


class CollectedTests(TestCase):
    def test_the_icons_reach_static_root(self):
        """WhiteNoise serves from STATIC_ROOT. An icon that exists in the
        source tree and was never collected 404s in production only."""
        root = Path(settings.STATIC_ROOT)
        if not root.exists():
            self.skipTest("STATIC_ROOT not collected in this environment")
        for name in list(EXPECTED_PNG) + ["favicon.ico", "og-card.png",
                                          "sauron_eye.svg"]:
            self.assertTrue((root / "logo" / name).exists(),
                            f"logo/{name} was never collected")
