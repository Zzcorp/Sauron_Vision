"""The lock's PIN takes the keyboard at once (2026-11-15).

The operator: "also make that the pin input is ready, what i mean is when
sauron is locked and the pin appears the user should be able to input
straight up from his keyboard the numbers, you understand on auto focus i
think is the term."

Measured on main (c37e841) in a headless Chromium, with real keys, a real
pointer and a real finger sent through the DevTools Input domain:

  * THE IN-APP LOCK (templates/base.html's #idleLockOverlay, driven by
    static/js/idle-lock.js), shown over an open page. After a click on the
    lock button the focus stayed ON the lock button, behind the veil. The
    document router leaves a button its own keys (its Enter is its own), so
    every digit was dropped, before the PIN showed and after: nothing could
    be typed until a box was clicked. The idle clock's lock left the focus
    on whatever was used last (a link of the menu: the same), a lock over a
    dialog left it on the dialog's button. The one focus() the wake made
    always missed: the card is visibility:hidden until its wake transition
    starts (its .04 s delay, then the frame that starts it), and a hidden
    box refuses the focus.
  * Gollum's "Lock the screen", chosen with Enter: that same Enter reached
    the lock's router as a submit, and the lock opened on "Enter at least 4
    digits.".
  * /locked/ (templates/dashboard/locked.html): its PIN showed with nothing
    focused (its wake gave no focus), and the digit that woke it left the
    keys on <body>; its document router still filled the boxes.

What is measured here, at 1440 x 900 and at a phone's 390 x 844:

  * the lock, asleep, still shows nothing to press (the sleeping contract,
    tests/test_lock_screen.py), and leaves nothing behind the veil holding
    the keys;
  * the moment the PIN shows (a move, a key, a touch), its first empty box
    has the keyboard: document.activeElement is that box; the digit that
    wakes it lands in the first box and the keys stay on the PIN; typed
    digits fill the boxes, in order (a phone's own keyboard too: text
    inserted where the focus is);
  * after a wrong PIN (the unlock view's own answer, asked through the real
    view) the cleared PIN has the keyboard again;
  * a focus taken behind the veil while the lock is up comes straight back;
  * a press on the lock's empty parts (where a phone's waking tap lands:
    its mousedown, after the PIN had the keys, gave them to <body>) leaves
    the keys on the PIN, and the keypad still types;
  * the submission is the one it was: one POST to /api/session/unlock/
    carrying exactly the digits typed;
  * /login/pin/, the login's second gate, as a guard: it already took the
    keyboard on load and after a wrong PIN (measured on main, unchanged).

Display and focus only: the same boxes, the same router, the same
submission, the same throttling and lockout (the server's). The PINs are
synthetic and nothing here logs one. The measured classes skip without a
Chromium.

Run with:  python manage.py test tests.test_lock_pin_focus
"""
import json
import pathlib
import re
import unittest

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from tests.test_close_advice import CHROME
from tests.test_magic_layer import _Browser, _file_page
from tests.test_ui_s0_fixes import _get

ROOT = pathlib.Path(settings.BASE_DIR)
HOST = "127.0.0.1"
#: The fixture operator's PIN, then what he types: a wrong one, then
#: another. All synthetic.
PIN, WRONG, AGAIN = "4321", "1357", "2468"
PAGE, LOCKED, LOGIN_PIN = "/positions/", "/locked/?next=/positions/", "/login/pin/"
DESK, PHONE = (1440, 900), (390, 844)
#: The shell's own scripts the lock rides on, in base.html's order: the
#: overlay controller, Gollum, the gate's nerves and the frame in the head,
#: idle-lock.js last.
SHELL_JS = ("sv-overlay.js", "sv-gollum.js", "sv-gate.js", "sv-frame.js", "idle-lock.js")

#: Where the keys are, read in the page: the PIN box that has the focus
#: (-1: none), what has it, whether it is behind the in-app veil, the
#: boxes filled (and their digits, for the order), whether the PIN shows,
#: the lock's own state and the error it says.
STATE = r"""JSON.stringify((function () {
  var a = document.activeElement;
  var boxes = [].slice.call(document.querySelectorAll('[data-il-pin], [data-lk-pin], #pinForm [data-pin]'));
  var veil = document.getElementById('idleLockOverlay');
  var err = document.getElementById('ilError') || document.getElementById('lkError')
            || document.getElementById('pinErrors');
  return {
    box: boxes.indexOf(a),
    on: a ? (a.id || a.tagName.toLowerCase()) : '',
    behind: !!(veil && a && a !== document.body && !veil.contains(a)),
    filled: boxes.map(function (b) { return b.value ? 'x' : '_'; }).join(''),
    typed: boxes.map(function (b) { return b.value; }).join(''),
    shown: boxes.length ? getComputedStyle(boxes[0]).visibility === 'visible' : false,
    locked: window.svIdleLock ? window.svIdleLock.isLocked() : null,
    error: err && !err.hidden && err.style.display !== 'none' ? err.textContent.trim() : ''
  };
})())"""

#: The JS conditions the measures wait on.
PIN_HAS_IT = ("(function () { var a = document.activeElement; return !!a && "
              "(a.hasAttribute('data-il-pin') || a.hasAttribute('data-lk-pin') || a.hasAttribute('data-pin')); })()")
ALL_FILLED = ("[].every.call(document.querySelectorAll('[data-il-pin], [data-lk-pin], #pinForm [data-pin]'), "
              "function (b) { return b.value; })")
REFUSED = ("(function () { var e = document.getElementById('ilError') || document.getElementById('lkError');"
           " var b = document.querySelectorAll('[data-il-pin], [data-lk-pin]');"
           " return !!e && !e.hidden && document.activeElement === b[0] && ![].some.call(b, function (x) { return x.value; }); })()")
LOCKED_UP = "!!window.svIdleLock && svIdleLock.isLocked()"

#: The idle clock passing the profile's window: the module's own check()
#: runs on a tab coming back into view, and finds the last activity more
#: than ten minutes old (the clock moved eleven).
CLOCK_PASSES = ("(function () { var real = Date.now; Date.now = function () { return real() + 11 * 60000; };"
                " document.dispatchEvent(new Event('visibilitychange')); })(); 0")


def _until(cond, ms=3000):
    """A promise that resolves once `cond` holds, or after `ms`: what
    "right after" may mean on a loaded machine, and no more."""
    return ("new Promise(function (ok) { var t0 = Date.now(); (function poll() {"
            " var v = false; try { v = !!(%s); } catch (e) {}"
            " if (v || Date.now() - t0 > %d) ok(v); else setTimeout(poll, 20); })(); })" % (cond, ms))


def _operator(name):
    """A signed-in operator with a PIN and the idle lock on (ten minutes)."""
    from portfolio.trader_profile import get_or_create_profile
    user = get_user_model().objects.create_user(name, password="x")
    prof = get_or_create_profile(user)
    prof.set_pin(PIN)
    prof.idle_lock_enabled = True
    prof.idle_lock_minutes = 10
    prof.save()
    client = Client()
    client.force_login(user)
    return client


def _refusal(client):
    """The unlock view's own answer to a wrong PIN, through the real view
    and its counted check (core/trading_pin): what the page's fetch gets.
    Leaves the session locked, which /locked/ needs to render."""
    client.post("/api/session/lock/", HTTP_HOST=HOST, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    resp = client.post("/api/session/unlock/", {"pin": WRONG}, HTTP_HOST=HOST,
                       HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    answer = json.loads(resp.content)
    if answer.get("status") != "error" or "attempts_left" not in answer:
        raise AssertionError("the unlock view no longer refuses a wrong PIN as it did: %r" % answer)
    return answer


def _server(answer):
    """The page's fetch, answered as the server answered: the unlock view's
    reply for /api/session/unlock/, an empty 204 for the lock and the ping.
    Every request is kept, url and body, for the submission's measure."""
    return ("window.__svSent = [];"
            "window.fetch = function (url, opts) {"
            " url = String(url); window.__svSent.push([url, String((opts && opts.body) || '')]);"
            " if (/\\/api\\/session\\/unlock\\//.test(url))"
            "  return Promise.resolve(new Response(%s, {status: 200, headers: {'Content-Type': 'application/json'}}));"
            " return Promise.resolve(new Response(null, {status: 204}));"
            "};" % json.dumps(json.dumps(answer)))


def _lock_tag(markup, locked=None):
    """idle-lock.js reads its settings off its own <script> tag (data-il-*),
    which _file_page drops with the page's scripts: it is put back, empty,
    with the attributes the server rendered. `locked` paints it as the
    server does for a session already locked (pin_locked)."""
    tag = re.search(r'<script\b[^>]*\bid="idleLockScript"[^>]*>', markup).group(0)
    attrs = dict(re.findall(r'(data-il-[a-z-]+)="([^"]*)"', tag))
    if locked is not None:
        attrs["data-il-locked"] = "1" if locked else "0"
    return ("(function () { var s = document.createElement('script'); s.id = 'idleLockScript';"
            + "".join("s.setAttribute(%s, %s);" % (json.dumps(k), json.dumps(v)) for k, v in sorted(attrs.items()))
            + " document.body.appendChild(s); })();")


def _standalone(markup, before=""):
    """A page that stands alone (no app shell: /locked/, /login/pin/) as a
    file Chromium opens: its own inline script kept (it IS the gate), the
    network's stylesheets dropped, /static/ read from the tree; `before`
    runs ahead of everything."""
    page = re.sub(r'<link\b[^>]*href="https?://[^>]*>', "", markup)
    page = page.replace("/static/", "file://%s/static/" % settings.BASE_DIR)
    i = page.index("<head>") + len("<head>")
    return page[:i] + ("<script>%s</script>" % before if before else "") + page[i:]


class _Hand:
    """One tab and a person at it: real keys, a real pointer and a finger,
    sent through the DevTools Input domain."""

    def __init__(self, browser, key, size, phone=False):
        self.b = browser
        if phone:
            self.sid = browser.chrome.page(size[0], size[1], True)
            self.call("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 1})
        else:
            self.sid = browser.tab(size[0], size[1])
        browser.open(self.sid, key)
        self.js(_until("document.readyState === 'complete'"))

    def call(self, method, params):
        return self.b.chrome.call(method, params, session=self.sid)

    def js(self, expression):
        return self.b.js(self.sid, expression)

    def state(self):
        return json.loads(self.js(STATE))

    def until(self, cond, ms=3000):
        self.js(_until(cond, ms))
        return self.state()

    def settle(self):
        """Two frames: whatever the last event scheduled has run."""
        self.js("new Promise(function (ok) { requestAnimationFrame(function () { requestAnimationFrame(ok); }); })")
        return self.state()

    def key(self, key, code, vk):
        for kind in ("rawKeyDown", "char", "keyUp"):
            if kind == "char" and len(key) != 1:
                continue
            p = {"type": kind, "key": key, "code": code,
                 "windowsVirtualKeyCode": vk, "nativeVirtualKeyCode": vk}
            if kind == "char":
                p["text"] = p["unmodifiedText"] = key
            self.call("Input.dispatchKeyEvent", p)

    def digits(self, text):
        for ch in text:
            self.key(ch, "Digit" + ch, 48 + int(ch))

    def enter(self):
        self.key("Enter", "Enter", 13)

    def soft_keys(self, text):
        """A phone's own keyboard: the text lands where the focus is, with
        no keydown at all (an IME commit)."""
        for ch in text:
            self.call("Input.insertText", {"text": ch})

    def move(self, x, y):
        self.call("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})

    def click(self, x, y):
        self.move(x, y)
        for kind in ("mousePressed", "mouseReleased"):
            self.call("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left",
                                                   "buttons": 1 if kind == "mousePressed" else 0,
                                                   "clickCount": 1})

    def tap(self, x, y):
        self.call("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y}]})
        self.call("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})

    def centre(self, selector):
        return json.loads(self.js(
            "JSON.stringify((function () { var r = document.querySelector(%s).getBoundingClientRect();"
            " return [r.left + r.width / 2, r.top + r.height / 2]; })())" % json.dumps(selector)))

    def sent(self):
        """The unlock POSTs the page made: their bodies."""
        return [body for url, body in json.loads(self.js("JSON.stringify(window.__svSent || [])"))
                if "/api/session/unlock/" in url]


def _shell_pages(name):
    """The app shell over an open page, as files: as the server renders it
    for an unlocked session, and as it renders it for a session already
    locked; and the unlock view's own answer to a wrong PIN."""
    client = _operator(name)
    markup = _get(client, PAGE)
    answer = _refusal(client)
    server = _server(answer)
    return {
        "shell": _file_page(markup, scripts=SHELL_JS, before=_lock_tag(markup) + server),
        "rendered": _file_page(markup, scripts=SHELL_JS, before=_lock_tag(markup, locked=True) + server),
    }


# ══════════════════════════════════════════════════════════════════════════
# The source: where the keys go, said once on each surface
# ══════════════════════════════════════════════════════════════════════════

class TheKeysGoToThePinSourceTests(SimpleTestCase):
    """The measures below are the proof; these say where it lives, for a
    machine with no Chromium."""

    def test_the_in_app_lock_gives_the_pin_the_keys_until_it_holds_them(self):
        js = (ROOT / "static/js/idle-lock.js").read_text(encoding="utf-8")
        self.assertIn("function takeKeys()", js)
        self.assertIn("function dropKeys()", js)
        wake = js.split("function wake()", 1)[1].split("function tickClock", 1)[0]
        self.assertIn("takeKeys()", wake)
        engage = js.split("function engage(", 1)[1].split("function release(", 1)[0]
        self.assertIn("dropKeys()", engage)
        self.assertIn('d.addEventListener("focusin"', js)
        take = js.split("function takeKeys()", 1)[1][:1400]
        self.assertIn("requestAnimationFrame", take)

    def test_the_locked_page_gives_the_pin_the_keys_when_it_wakes(self):
        page = (ROOT / "templates/dashboard/locked.html").read_text(encoding="utf-8")
        self.assertIn("function takeKeys()", page)
        wake = page.split("function wake()", 1)[1][:400]
        self.assertIn("takeKeys()", wake)

    def test_a_key_pressed_before_the_lock_showed_is_not_typed_into_it(self):
        js = (ROOT / "static/js/idle-lock.js").read_text(encoding="utf-8")
        engage = js.split("function engage(", 1)[1].split("function release(", 1)[0]
        self.assertIn("lockedSince = ", engage)
        router = js.split("if (!isLocked) return;", 1)[1][:200]
        self.assertIn("if (beforeTheLock(e)) return;", router)
        wakes = js.split('["mousemove", "keydown", "touchstart", "pointerdown"]', 1)[1][:600]
        self.assertIn("!beforeTheLock(e)", wakes)


# ══════════════════════════════════════════════════════════════════════════
# Measured: the in-app lock over an open page
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheInAppLockTakesTheKeyboardTests(TestCase):
    """The lock shown over /positions/ at 1440 x 900: by the lock button, by
    the idle clock, over a dialog, by Gollum, and painted at load."""

    @classmethod
    def setUpTestData(cls):
        b = _Browser(_shell_pages("lockfocus_desk"), "sv-lockfocus-")
        g = cls.got = {}
        try:
            # 1. The lock button, then the digits straight away: the first
            #    one wakes the lock.
            h = _Hand(b, "shell", DESK)
            x, y = h.centre("#lockNowBtn")
            h.click(x, y)
            h.until(LOCKED_UP)
            g["button.asleep"] = h.settle()
            h.digits(WRONG[0])
            g["button.first"] = h.until(PIN_HAS_IT + " && document.activeElement === "
                                        "document.querySelectorAll('[data-il-pin]')[1]")
            h.digits(WRONG[1:])
            g["button.typed"] = h.until(ALL_FILLED)
            h.enter()
            g["button.refused"] = h.until(REFUSED)
            g["button.sent"] = h.sent()
            h.digits(AGAIN)
            g["button.again"] = h.until(ALL_FILLED)

            # 2. The lock button, then a move: the PIN shows with the keys.
            h = _Hand(b, "shell", DESK)
            x, y = h.centre("#lockNowBtn")
            h.click(x, y)
            h.until(LOCKED_UP)
            h.move(700, 420)
            g["move.pin"] = h.until(PIN_HAS_IT)
            h.digits(AGAIN)
            g["move.typed"] = h.until(ALL_FILLED)

            # 3. The idle clock locks the page with a link of the menu
            #    focused (the last thing the operator used).
            h = _Hand(b, "shell", DESK)
            h.js("document.querySelector('#mainSidebar .sidebar-nav a.nav-link').focus(); 0")
            g["clock.before"] = h.state()
            h.js(CLOCK_PASSES)
            h.until(LOCKED_UP)
            g["clock.asleep"] = h.settle()
            h.move(700, 420)
            g["clock.pin"] = h.until(PIN_HAS_IT)
            h.digits(AGAIN)
            g["clock.typed"] = h.until(ALL_FILLED)

            # 4. A dialog holds the focus when the lock comes (the health
            #    poll's 423 calls svIdleLock.engage(false), base.html).
            h = _Hand(b, "shell", DESK)
            h.js("SV.overlay.confirm({title: 'A dialog behind', message: 'It holds the focus.',"
                 " confirmLabel: 'OK'}); 0")
            g["dialog.before"] = h.until("!!document.activeElement.closest('.sv-dialog')")
            h.js("svIdleLock.engage(false); 0")
            h.until(LOCKED_UP)
            g["dialog.asleep"] = h.settle()
            h.move(700, 420)
            g["dialog.pin"] = h.until(PIN_HAS_IT)
            h.digits(AGAIN)
            g["dialog.typed"] = h.until(ALL_FILLED)

            # 5. Something behind the veil takes the focus while the lock is
            #    up: asleep, then with the PIN showing.
            h = _Hand(b, "shell", DESK)
            x, y = h.centre("#lockNowBtn")
            h.click(x, y)
            h.until(LOCKED_UP)
            h.js("document.getElementById('svCmd').focus(); 0")
            g["grab.asleep"] = h.settle()
            h.move(700, 420)
            h.until(PIN_HAS_IT)
            h.js("document.getElementById('svCmd').focus(); 0")
            g["grab.awake"] = h.until(PIN_HAS_IT)
            h.digits(AGAIN)
            g["grab.typed"] = h.until(ALL_FILLED)
            g["grab.field"] = h.js("document.getElementById('svCmd').value")

            # 6. Gollum's "Lock the screen", chosen with Enter.
            h = _Hand(b, "shell", DESK)
            x, y = h.centre("#gollumFab")
            h.click(x, y)
            h.until("document.activeElement && document.activeElement.hasAttribute('data-gollum-input')")
            h.soft_keys("lock")
            h.key("ArrowDown", "ArrowDown", 40)
            h.enter()
            h.until(LOCKED_UP)
            g["gollum.locked"] = h.settle()
            h.digits(AGAIN[0])
            g["gollum.first"] = h.until(PIN_HAS_IT + " && document.activeElement === "
                                        "document.querySelectorAll('[data-il-pin]')[1]")

            # 7. The page painted locked at load (the server's pin_locked).
            h = _Hand(b, "rendered", DESK)
            h.until(LOCKED_UP)
            g["rendered.asleep"] = h.settle()
            h.move(700, 420)
            g["rendered.pin"] = h.until(PIN_HAS_IT)
            h.digits(AGAIN)
            g["rendered.typed"] = h.until(ALL_FILLED)

            # 8. A click on the veil's empty corner, then a key of the pad.
            h = _Hand(b, "shell", DESK)
            x, y = h.centre("#lockNowBtn")
            h.click(x, y)
            h.until(LOCKED_UP)
            h.move(700, 420)
            h.until(PIN_HAS_IT)
            h.click(12, 12)
            g["veil.click"] = h.settle()
            x, y = h.centre('#idleLockOverlay [data-gate-key="7"]')
            h.click(x, y)
            g["veil.pad"] = h.until(PIN_HAS_IT + " && document.activeElement === "
                                    "document.querySelectorAll('[data-il-pin]')[1]")
        finally:
            b.close()

    def _asleep_and_clear(self, st):
        """The lock is up, asleep (nothing to press shows), and nothing
        behind the veil holds the keys."""
        self.assertTrue(st["locked"], st)
        self.assertFalse(st["shown"], st)
        self.assertFalse(st["behind"], st)

    def test_the_lock_button_leaves_nothing_behind_the_veil_holding_the_keys(self):
        """main: the focus stayed on the lock button itself."""
        self._asleep_and_clear(self.got["button.asleep"])

    def test_a_digit_typed_to_wake_it_lands_in_the_first_box_and_the_keys_stay_on_the_pin(self):
        """main: the digit was dropped (the focus on the lock button) and so
        was every one after it."""
        st = self.got["button.first"]
        self.assertEqual(st["filled"], "x___", st)
        self.assertEqual(st["box"], 1, st)
        st = self.got["button.typed"]
        self.assertEqual(st["typed"], WRONG, st)
        self.assertEqual(st["box"], 3, st)

    def test_the_submission_is_the_one_it_was(self):
        """One POST to /api/session/unlock/, carrying exactly the digits
        typed: the same field, the same submission."""
        self.assertEqual(self.got["button.sent"], ["pin=" + WRONG])

    def test_after_a_wrong_pin_the_cleared_pin_has_the_keyboard_again(self):
        st = self.got["button.refused"]
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(st["filled"], "____", st)
        self.assertIn("Incorrect PIN.", st["error"])
        self.assertIn("attempts left", st["error"])
        self.assertEqual(self.got["button.again"]["typed"], AGAIN, self.got["button.again"])

    def test_the_pin_a_move_shows_has_the_keyboard(self):
        """main: the PIN showed, the focus stayed on the lock button."""
        st = self.got["move.pin"]
        self.assertTrue(st["shown"], st)
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(self.got["move.typed"]["typed"], AGAIN, self.got["move.typed"])

    def test_the_idle_clock_s_lock_takes_the_keys_from_a_link_behind(self):
        """main: the focus stayed on the link, behind the veil."""
        self.assertEqual(self.got["clock.before"]["on"], "a", self.got["clock.before"])
        self._asleep_and_clear(self.got["clock.asleep"])
        self.assertEqual(self.got["clock.pin"]["box"], 0, self.got["clock.pin"])
        self.assertEqual(self.got["clock.typed"]["typed"], AGAIN, self.got["clock.typed"])

    def test_a_lock_over_a_dialog_takes_the_keys_from_it(self):
        """main: the focus stayed on the dialog's button behind the veil."""
        self.assertEqual(self.got["dialog.before"]["on"], "button", self.got["dialog.before"])
        self._asleep_and_clear(self.got["dialog.asleep"])
        self.assertEqual(self.got["dialog.pin"]["box"], 0, self.got["dialog.pin"])
        self.assertEqual(self.got["dialog.typed"]["typed"], AGAIN, self.got["dialog.typed"])

    def test_a_focus_taken_behind_the_veil_comes_straight_back(self):
        """main: the command field kept the focus it took."""
        self._asleep_and_clear(self.got["grab.asleep"])
        self.assertEqual(self.got["grab.awake"]["box"], 0, self.got["grab.awake"])
        self.assertEqual(self.got["grab.typed"]["typed"], AGAIN, self.got["grab.typed"])
        self.assertEqual(self.got["grab.field"], "")

    def test_the_enter_that_asked_gollum_for_the_lock_is_not_typed_into_it(self):
        """main: the lock opened on "Enter at least 4 digits."."""
        st = self.got["gollum.locked"]
        self.assertEqual(st["error"], "", st)
        self._asleep_and_clear(st)
        st = self.got["gollum.first"]
        self.assertEqual(st["filled"], "x___", st)
        self.assertEqual(st["box"], 1, st)

    def test_a_page_painted_locked_takes_the_keys_when_the_pin_shows(self):
        self._asleep_and_clear(self.got["rendered.asleep"])
        self.assertEqual(self.got["rendered.pin"]["box"], 0, self.got["rendered.pin"])
        self.assertEqual(self.got["rendered.typed"]["typed"], AGAIN, self.got["rendered.typed"])

    def test_a_click_on_the_veil_s_empty_parts_leaves_the_keys_on_the_pin(self):
        """A press on the eye, the hour or the margins is no choice of where
        the keys go (a phone's waking tap lands there)."""
        st = self.got["veil.click"]
        self.assertEqual(st["box"], 0, st)

    def test_the_pad_still_types_and_gives_the_keys_back_to_the_pin(self):
        """A key of the pad keeps its own press: the digit lands, the keys
        go back to the next box (static/js/sv-gate.js, unchanged)."""
        st = self.got["veil.pad"]
        self.assertEqual(st["filled"], "x___", st)
        self.assertEqual(st["typed"], "7", st)
        self.assertEqual(st["box"], 1, st)


@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheInAppLockOnAPhoneTests(TestCase):
    """The same lock at 390 x 844, a phone's viewport with touch: the clock
    locks the page while it was away (its return into view), a tap wakes
    it, the phone's own keyboard types."""

    @classmethod
    def setUpTestData(cls):
        b = _Browser(_shell_pages("lockfocus_phone"), "sv-lockfocus-phone-")
        g = cls.got = {}
        try:
            h = _Hand(b, "shell", PHONE, phone=True)
            h.js("document.getElementById('userMenuTrigger').focus(); 0")
            g["before"] = h.state()
            h.js(CLOCK_PASSES)
            h.until(LOCKED_UP)
            g["asleep"] = h.settle()
            h.tap(12, 12)
            g["pin"] = h.until(PIN_HAS_IT)
            h.soft_keys(WRONG)
            g["typed"] = h.until(ALL_FILLED)
            h.enter()
            g["refused"] = h.until(REFUSED)
            g["sent"] = h.sent()
            h.digits(AGAIN)
            g["again"] = h.until(ALL_FILLED)
        finally:
            b.close()

    def test_nothing_behind_the_veil_keeps_the_keys(self):
        self.assertEqual(self.got["before"]["on"], "userMenuTrigger", self.got["before"])
        st = self.got["asleep"]
        self.assertTrue(st["locked"], st)
        self.assertFalse(st["shown"], st)
        self.assertFalse(st["behind"], st)

    def test_the_pin_a_tap_shows_has_the_keyboard(self):
        st = self.got["pin"]
        self.assertTrue(st["shown"], st)
        self.assertEqual(st["box"], 0, st)

    def test_the_phone_s_own_keyboard_types_into_it(self):
        """Text inserted where the focus is: with no box focused, nothing."""
        self.assertEqual(self.got["typed"]["typed"], WRONG, self.got["typed"])

    def test_after_a_wrong_pin_the_cleared_pin_has_the_keyboard_again(self):
        st = self.got["refused"]
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(st["filled"], "____", st)
        self.assertEqual(self.got["sent"], ["pin=" + WRONG])
        self.assertEqual(self.got["again"]["typed"], AGAIN, self.got["again"])


# ══════════════════════════════════════════════════════════════════════════
# Measured: /locked/, the page a locked session gets
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheLockedPageTakesTheKeyboardTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        client = _operator("lockfocus_locked")
        answer = _refusal(client)
        markup = _get(client, LOCKED)
        b = _Browser({"locked": _standalone(markup, _server(answer))}, "sv-lockfocus-locked-")
        g = cls.got = {}
        try:
            # A move wakes it; a wrong PIN; the next one.
            h = _Hand(b, "locked", DESK)
            g["load"] = h.settle()
            h.move(700, 300)
            g["move.pin"] = h.until(PIN_HAS_IT)
            h.click(12, 12)
            g["move.click"] = h.settle()
            h.digits(WRONG)
            g["move.typed"] = h.until(ALL_FILLED)
            h.enter()
            g["move.refused"] = h.until(REFUSED)
            g["move.sent"] = h.sent()
            h.digits(AGAIN)
            g["move.again"] = h.until(ALL_FILLED)

            # A digit wakes it.
            h = _Hand(b, "locked", DESK)
            h.digits(AGAIN[0])
            g["key.first"] = h.until(PIN_HAS_IT + " && document.activeElement === "
                                     "document.querySelectorAll('[data-lk-pin]')[1]")

            # A phone: a tap wakes it, its own keyboard types.
            h = _Hand(b, "locked", PHONE, phone=True)
            g["phone.load"] = h.settle()
            h.tap(12, 12)
            g["phone.pin"] = h.until(PIN_HAS_IT)
            h.soft_keys(WRONG)
            g["phone.typed"] = h.until(ALL_FILLED)
            h.enter()
            g["phone.refused"] = h.until(REFUSED)
        finally:
            b.close()

    def test_it_loads_asleep_with_nothing_to_press(self):
        """The sleeping contract stands: no PIN shows, so none is focused."""
        for key in ("load", "phone.load"):
            st = self.got[key]
            with self.subTest(key):
                self.assertFalse(st["shown"], st)
                self.assertEqual(st["box"], -1, st)

    def test_the_pin_a_move_shows_has_the_keyboard(self):
        """main: the PIN showed with the keys on <body>."""
        st = self.got["move.pin"]
        self.assertTrue(st["shown"], st)
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(self.got["move.typed"]["typed"], WRONG, self.got["move.typed"])

    def test_a_click_on_the_page_s_empty_parts_leaves_the_keys_on_the_pin(self):
        st = self.got["move.click"]
        self.assertEqual(st["box"], 0, st)

    def test_a_digit_typed_to_wake_it_lands_in_the_first_box_and_the_keys_stay_on_the_pin(self):
        """main: the digit landed, the keys stayed on <body>."""
        st = self.got["key.first"]
        self.assertEqual(st["filled"], "x___", st)
        self.assertEqual(st["box"], 1, st)

    def test_after_a_wrong_pin_the_cleared_pin_has_the_keyboard_again(self):
        st = self.got["move.refused"]
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(st["filled"], "____", st)
        self.assertIn("Incorrect PIN.", st["error"])
        self.assertEqual(self.got["move.sent"], ["pin=" + WRONG])
        self.assertEqual(self.got["move.again"]["typed"], AGAIN, self.got["move.again"])

    def test_on_a_phone_a_tap_shows_the_pin_with_the_keyboard(self):
        st = self.got["phone.pin"]
        self.assertTrue(st["shown"], st)
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(self.got["phone.typed"]["typed"], WRONG, self.got["phone.typed"])
        st = self.got["phone.refused"]
        self.assertEqual(st["box"], 0, st)
        self.assertEqual(st["filled"], "____", st)


# ══════════════════════════════════════════════════════════════════════════
# Measured guard: /login/pin/, the login's second gate (unchanged)
# ══════════════════════════════════════════════════════════════════════════

@unittest.skipUnless(CHROME, "no headless Chromium on this machine")
class TheLoginGateKeepsTheKeyboardTests(TestCase):
    """It took the keyboard on load already (its script focuses the first
    box; a wrong PIN renders the page again). Measured so it stays so."""

    @classmethod
    def setUpTestData(cls):
        from core import security
        from portfolio.trader_profile import get_or_create_profile
        security._login_attempts.clear()
        user = get_user_model().objects.create_user("lockfocus_login", password="correct-horse")
        prof = get_or_create_profile(user)
        prof.set_pin(PIN)
        prof.save()
        client = Client()
        client.post("/login/", {"username": "lockfocus_login", "password": "correct-horse"}, HTTP_HOST=HOST)
        gate = client.get(LOGIN_PIN, HTTP_HOST=HOST).content.decode()
        refused = client.post(LOGIN_PIN, {"pin": WRONG}, HTTP_HOST=HOST).content.decode()
        security._login_attempts.clear()
        if "SECOND GATE" not in gate or "Invalid PIN" not in refused:
            raise AssertionError("the login's PIN step no longer renders as it did")
        b = _Browser({"gate": _standalone(gate), "refused": _standalone(refused)}, "sv-lockfocus-login-")
        g = cls.got = {}
        try:
            h = _Hand(b, "gate", DESK)
            g["load"] = h.until(PIN_HAS_IT)
            h.digits(WRONG)
            g["typed"] = h.until(ALL_FILLED)
            h = _Hand(b, "refused", DESK)
            g["refused"] = h.until(PIN_HAS_IT)
            h = _Hand(b, "gate", PHONE, phone=True)
            g["phone"] = h.until(PIN_HAS_IT)
        finally:
            b.close()

    def test_the_pin_has_the_keyboard_on_load(self):
        for key in ("load", "phone"):
            with self.subTest(key):
                self.assertEqual(self.got[key]["box"], 0, self.got[key])

    def test_typed_digits_land_in_it(self):
        self.assertEqual(self.got["typed"]["typed"], WRONG, self.got["typed"])

    def test_after_a_wrong_pin_the_page_comes_back_with_the_keyboard_on_the_pin(self):
        st = self.got["refused"]
        self.assertEqual(st["box"], 0, st)
        self.assertIn("Invalid PIN", st["error"])
