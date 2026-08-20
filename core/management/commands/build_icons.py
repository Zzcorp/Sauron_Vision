"""Rasterize the Sauron mark into every icon the platform actually serves.

One vector source, many rasters. The alternative — hand-made PNGs — is how
`manifest.json` ended up pointing at `sauron_192.png` and `sauron_512.png`,
neither of which existed, for however long the PWA had been shipping.

    python manage.py build_icons            # regenerate everything
    python manage.py build_icons --list     # say what would be written

WHY THIS IS A COMMAND AND NOT A BUILD STEP
------------------------------------------
It needs a browser to rasterize, and CI does not have one. The generated
PNGs are therefore COMMITTED, like any other static asset, and this command
is what you run when the vector changes. `tests/test_brand_assets.py` checks
the committed files exist at the right dimensions, which is the part that
can run anywhere.

WHY A BROWSER
-------------
There is no SVG rasterizer in this project's dependency set (no cairosvg, no
svglib) and adding one to requirements.txt for an occasional design task
would put a native-code dependency into every deploy. Chrome is already on
any machine a person designs icons on. Rendering is done at the source's
native size and downsampled with Lanczos rather than re-rendered small:
below about 64px a browser's own rasterizer starts dropping thin strokes
entirely, and a favicon that loses its pupil is worse than a soft one.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# Windows, macOS and Linux locations, in the order worth trying. Chrome is
# named first because it is the one this was developed against; Edge shares
# the engine and produces identical output.
CHROME_CANDIDATES = (
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)
CHROME_ON_PATH = ("google-chrome", "chromium", "chromium-browser", "chrome")

LOGO_DIR = Path(settings.BASE_DIR) / "static" / "logo"

# The square mark, and what it becomes.
#
# 16/32 are the browser tab. 48 exists only inside the .ico (Windows uses it
# for the taskbar). 180 is apple-touch-icon — Safari's home-screen tile,
# which is composited on an unknown background and is why the mark carries
# its own ground rather than relying on transparency. 192/512 are the PWA
# manifest sizes, and 512 doubles as the file anything else can start from.
SQUARE_TARGETS = {
    "favicon-16.png": 16,
    "favicon-32.png": 32,
    "apple-touch-icon.png": 180,
    "sauron_192.png": 192,
    "sauron_512.png": 512,
}
# Multi-resolution .ico for the browsers and OS surfaces that still ask for
# one by that name (and for /favicon.ico requested at the root by crawlers
# that never read the <link> tags).
ICO_SIZES = (16, 32, 48)

# The share card. 1200x630 is the size Facebook, LinkedIn, Slack and X all
# document, and the aspect ratio twitter:card=summary_large_image crops to.
# A square logo posted into that slot gets letterboxed with grey bars, which
# is what the old logo_SV.png did on every link ever shared.
OG_SOURCE = "sauron_og.svg"
OG_OUTPUT = "og-card.png"
OG_SIZE = (1200, 630)

SQUARE_SOURCE = "sauron_eye.svg"
SQUARE_RENDER = 1024      # render big, downsample sharp


def find_browser() -> str:
    for path in CHROME_CANDIDATES:
        if os.path.exists(path):
            return path
    for name in CHROME_ON_PATH:
        found = shutil.which(name)
        if found:
            return found
    raise CommandError(
        "No Chrome/Chromium/Edge found. This command rasterizes SVG with a "
        "browser rather than adding a native rasterizer to requirements.txt "
        "— see the module docstring. The generated PNGs are committed, so "
        "you only need this when the vector source changes.")


# The share card sets its wordmark in the platform's own display face, which
# is a Google font the app loads over the network and which is not installed
# on any machine by default. Chrome fetches it while rendering; offline, the
# stack in the SVG falls back to a local geometric sans and the card is still
# a card. The SQUARE mark carries no text at all and never needs this — a
# favicon with a font dependency is a favicon that renders differently on
# every machine that regenerates it.
FONT_LINK = (
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    'family=Orbitron:wght@700;900&family=Rajdhani:wght@500;600&display=block"'
    ' rel="stylesheet">'
)


def render_svg(browser: str, svg_path: Path, out_png: Path,
               width: int, height: int, *, webfonts: bool = False) -> None:
    """Screenshot `svg_path` at exactly width x height, transparent ground.

    The SVG is wrapped in a zero-margin HTML page rather than loaded
    directly: a bare SVG inherits the browser's 8px body margin and its own
    intrinsic sizing, so "512x512 window" silently became "496x496 image
    offset by 8" — and the offset only shows up as a shaved edge at 16px,
    which is exactly the size nobody inspects.
    """
    svg = svg_path.read_text(encoding="utf-8")
    html = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        + (FONT_LINK if webfonts else "") +
        "<style>"
        "html,body{margin:0;padding:0;background:transparent;}"
        f"svg{{display:block;width:{width}px;height:{height}px;}}"
        "</style></head><body>" + svg + "</body></html>"
    )
    with tempfile.TemporaryDirectory(prefix="sv-icons-") as tmp:
        page = Path(tmp) / "page.html"
        page.write_text(html, encoding="utf-8")
        shot = Path(tmp) / "shot.png"
        proc = subprocess.run([
            browser, "--headless", "--disable-gpu", "--no-sandbox",
            "--hide-scrollbars", "--force-device-scale-factor=1",
            "--default-background-color=00000000",
            f"--screenshot={shot}",
            f"--window-size={width},{height}",
            page.as_uri(),
        ], capture_output=True, text=True, timeout=180)
        if not shot.exists():
            raise CommandError(
                f"{browser} produced no image for {svg_path.name}: "
                f"{(proc.stderr or proc.stdout or '')[:400]}")
        out_png.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(shot, out_png)


class Command(BaseCommand):
    help = "Rasterize static/logo/sauron_eye.svg into every served icon size."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list", action="store_true",
            help="Print what would be written and exit, touching nothing.")

    def handle(self, *args, **options):
        from PIL import Image

        planned = [LOGO_DIR / n for n in SQUARE_TARGETS]
        planned += [LOGO_DIR / "favicon.ico", LOGO_DIR / OG_OUTPUT]
        if options["list"]:
            for path in planned:
                self.stdout.write(str(path))
            return

        square_src = LOGO_DIR / SQUARE_SOURCE
        if not square_src.exists():
            raise CommandError(f"missing vector source: {square_src}")

        browser = find_browser()
        self.stdout.write(f"rasterizing with {browser}")

        with tempfile.TemporaryDirectory(prefix="sv-master-") as tmp:
            master_path = Path(tmp) / "master.png"
            render_svg(browser, square_src, master_path,
                       SQUARE_RENDER, SQUARE_RENDER)
            master = Image.open(master_path).convert("RGBA")

            for name, size in sorted(SQUARE_TARGETS.items(),
                                     key=lambda kv: -kv[1]):
                out = LOGO_DIR / name
                master.resize((size, size), Image.LANCZOS).save(out, "PNG")
                self.stdout.write(f"  {name:<24} {size}x{size}")

            # One .ico carrying every size, so the OS picks its own.
            ico = LOGO_DIR / "favicon.ico"
            master.resize((max(ICO_SIZES),) * 2, Image.LANCZOS).save(
                ico, format="ICO",
                sizes=[(s, s) for s in ICO_SIZES])
            self.stdout.write(f"  {'favicon.ico':<24} {list(ICO_SIZES)}")

        og_src = LOGO_DIR / OG_SOURCE
        if og_src.exists():
            og_out = LOGO_DIR / OG_OUTPUT
            with tempfile.TemporaryDirectory(prefix="sv-og-") as tmp:
                raw = Path(tmp) / "og.png"
                render_svg(browser, og_src, raw, *OG_SIZE, webfonts=True)
                # Flattened onto the card's own ground: a share card with an
                # alpha channel gets composited on whatever the client feels
                # like, and half of them choose white.
                card = Image.open(raw).convert("RGBA")
                # --bg-void, the platform's own ground (#030806).
                ground = Image.new("RGBA", card.size, (3, 8, 6, 255))
                Image.alpha_composite(ground, card).convert("RGB").save(
                    og_out, "PNG", optimize=True)
            self.stdout.write(f"  {OG_OUTPUT:<24} {OG_SIZE[0]}x{OG_SIZE[1]}")
        else:
            self.stdout.write(self.style.WARNING(
                f"  no {OG_SOURCE} — share card not rebuilt"))

        self.stdout.write(self.style.SUCCESS(
            "done — commit the PNGs, they are the artefact CI serves"))
