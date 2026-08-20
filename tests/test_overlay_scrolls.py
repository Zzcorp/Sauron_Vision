"""A popup the operator cannot scroll is a popup with no content.

Reported as two symptoms that turned out to be one bug: "many popups still
can't be scrolled" and "they close before that". The panels are portalled
to <body> and re-anchored to their trigger on scroll, with the listener in
the CAPTURE phase — necessary, because a trigger inside its own scrolling
region never bubbles a scroll to window.

The cost of capture is that it also hears scrolls that ORIGINATE INSIDE the
overlay. Re-anchoring on one of those recomputes `top` from the trigger and
snaps the panel back to the top mid-scroll: a panel that refuses to move.
And when the snap drags it out from under the pointer, whatever closes on
pointer-leave closes it — the "it shuts before I can read it" half.

The guard is one condition, so it is tested by RUNNING it rather than by
grepping for it: a scroll whose target is inside the overlay must not
re-anchor, and a scroll on the document or the window must.

Run with:  python manage.py test tests.test_overlay_scrolls
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

NODE = shutil.which("node")
OVERLAY = Path(settings.BASE_DIR) / "static" / "js" / "sv-overlay.js"

#: Rebuilds the guard from the shipped source and drives it with fake
#: scroll events. `anchor()` is replaced by a counter, so "did it
#: re-anchor?" is answerable without a layout engine.
HARNESS = r"""
const fs = require("fs");
const src = fs.readFileSync(process.argv[2], "utf8");

// The guard, lifted verbatim from the file so the test cannot drift from
// the shipped code: everything between the assignment and its closing
// brace, with `anchor(el, trigger)` swapped for a counter.
const m = src.match(/el\._svAnchor = function \(e\) \{([\s\S]*?)\n        \};/);
if (!m) { console.log(JSON.stringify({error: "guard not found in source"})); process.exit(0); }

let body = m[1].replace(/anchor\(el, trigger\);/, "hits++;");
if (body === m[1]) { console.log(JSON.stringify({error: "anchor call not found"})); process.exit(0); }

let hits = 0;
const d = { nodeName: "#document" };
const windowObj = { nodeName: "#window" };
const inside = { nodeName: "INSIDE" };
const outside = { nodeName: "OUTSIDE" };
const el = { contains: (n) => n === inside };

const guard = new Function("e", "d", "window", "el", "hits_ref",
    "let hits = hits_ref.n;" + body + "\nhits_ref.n = hits;");

function fire(target) {
    const ref = { n: hits };
    guard({ target }, d, windowObj, el, ref);
    const moved = ref.n > hits;
    hits = ref.n;
    return moved;
}

console.log(JSON.stringify({
    inside_the_panel: fire(inside),
    on_the_document: fire(d),
    on_the_window: fire(windowObj),
    elsewhere_on_the_page: fire(outside),
    no_target_at_all: fire(null),
}));
"""


@unittest.skipIf(NODE is None, "node is not installed on this machine")
class AnchorGuardTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with tempfile.TemporaryDirectory() as tmp:
            runner = Path(tmp) / "guard.js"
            runner.write_text(HARNESS, encoding="utf-8")
            proc = subprocess.run(
                [NODE, str(runner), str(OVERLAY)],
                capture_output=True, text=True, timeout=60)
        assert proc.returncode == 0, proc.stderr[:2000]
        cls.out = json.loads(proc.stdout.strip().splitlines()[-1])
        assert "error" not in cls.out, cls.out.get("error")

    def test_scrolling_inside_the_panel_does_not_snap_it_back(self):
        """The bug itself. Re-anchoring here is what made the panel refuse
        to scroll and then close under the pointer."""
        self.assertFalse(self.out["inside_the_panel"])

    def test_scrolling_the_page_still_re_anchors(self):
        """The other half: the panel is position:fixed against a trigger
        that moves with the page. Not following it is just as broken."""
        self.assertTrue(self.out["on_the_document"])
        self.assertTrue(self.out["on_the_window"])

    def test_a_scroll_in_some_other_region_still_re_anchors(self):
        """A sibling scroll container can move the trigger too."""
        self.assertTrue(self.out["elsewhere_on_the_page"])

    def test_an_event_with_no_target_re_anchors_rather_than_throwing(self):
        self.assertTrue(self.out["no_target_at_all"])


class ListenerRegistrationTests(SimpleTestCase):
    """The guard is only reachable if the listener is still registered the
    way it was — and only removable if teardown matches the capture flag."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.js = OVERLAY.read_text(encoding="utf-8")

    def test_the_scroll_listener_is_still_in_the_capture_phase(self):
        self.assertIn('window.addEventListener("scroll", el._svAnchor, true)',
                      self.js)

    def test_it_is_removed_with_the_same_capture_flag(self):
        """removeEventListener without the matching flag removes NOTHING,
        so every open would leak another anchor listener onto window."""
        self.assertIn(
            'window.removeEventListener("scroll", el._svAnchor, true)',
            self.js)

    def test_the_panel_is_allowed_to_scroll_at_all(self):
        css = (Path(settings.BASE_DIR) / "static" / "css" / "sv-overlay.css") \
            .read_text(encoding="utf-8")
        block = css.split(".ip-dropdown {", 1)[1].split("}", 1)[0] \
            if ".ip-dropdown {" in css else ""
        sauron = (Path(settings.BASE_DIR) / "static" / "css" / "sauron.css") \
            .read_text(encoding="utf-8")
        if not block:
            block = sauron.split(".ip-dropdown {", 1)[1].split("}", 1)[0]
        self.assertIn("overflow-y: auto", block)
