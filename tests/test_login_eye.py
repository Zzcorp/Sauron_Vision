"""The eye on the access key: the login page shows a typed password on request.

The operator, 2026-09-28: "ajouter dans le système de login un petit œil
vert à l'image de Sauron pour pouvoir voir son mot de passe tapé" — and,
asked whether the PIN page should get one too: "not the pin, the password
input". So: one eye, on the login page's Access Key field, nowhere else.

What these tests pin (templates/registration/_key_eye.html):

  * The key is HIDDEN when the page renders. The eye reveals it on a
    press, never on load — a page that showed the password by default
    would be a shoulder-surfer's page.
  * The eye is a button that cannot submit the form (type="button"), and
    it names what it does for a screen reader (aria-pressed, aria-label,
    aria-controls on the input it reveals).
  * It is Sauron's eye, not a stock icon: the mark's evenodd lid band, an
    iris, a pupil knocked out in the ground colour — painted in
    currentColor so its state is a colour the stylesheet sets (dim and
    shut while hidden, lit and open while shown).
  * A revealed key is never the state a page is left in: the script hides
    it again on submit and when the page goes to the background.
  * The PIN page does not get one.

Run with:  python manage.py test tests.test_login_eye
"""
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase

from core import security
from portfolio.trader_profile import get_or_create_profile


def _template(rel):
    for engine in settings.TEMPLATES:
        for d in engine.get("DIRS", []):
            path = Path(d) / rel
            if path.exists():
                return path.read_text(encoding="utf-8")
    raise AssertionError(f"template not found: {rel}")


def _tag(body, tag, **attrs):
    """The first <tag ...> whose attributes carry every given value."""
    for m in re.finditer(rf"<{tag}\b[^>]*>", body):
        if all(f'{k}="{v}"' in m.group(0) for k, v in attrs.items()):
            return m.group(0)
    return None


class TheEyeOnTheLoginPageTests(TestCase):

    def setUp(self):
        self.body = self.client.get("/login/").content.decode()

    def test_the_key_is_hidden_when_the_page_renders(self):
        field = _tag(self.body, "input", id="id_password")
        self.assertIsNotNone(field, "the Access Key field is gone")
        self.assertIn('type="password"', field)

    def test_the_eye_stands_beside_the_key_and_names_it(self):
        eye = _tag(self.body, "button", **{"class": "key-eye"})
        self.assertIsNotNone(eye, "no eye on the login page")
        self.assertIn('data-for="id_password"', eye)
        self.assertIn('aria-controls="id_password"', eye)
        self.assertIn('aria-pressed="false"', eye)
        self.assertIn('aria-label="Show the access key"', eye)

    def test_the_eye_can_never_submit_the_form(self):
        eye = _tag(self.body, "button", **{"class": "key-eye"})
        self.assertIn('type="button"', eye)

    def test_the_key_and_the_eye_share_one_wrap(self):
        """The eye is positioned against the field, not the card: the wrap
        is what the stylesheet anchors it to."""
        self.assertRegex(
            self.body,
            r'<div class="key-wrap"><input[^>]*id="id_password"[^>]*>\s*<button[^>]*class="key-eye"')

    def test_it_is_saurons_eye_painted_in_the_current_colour(self):
        """Shut and open are two groups of one SVG; the colour is the
        button's, so the stylesheet's states (dim, lit) are the whole of
        the state change."""
        start = self.body.index('class="key-eye"')
        svg = self.body[start:self.body.index("</svg>", start)]
        self.assertIn('fill-rule="evenodd"', svg)          # the mark's lid band
        self.assertIn('class="eye-open"', svg)
        self.assertIn('class="eye-shut"', svg)
        self.assertIn('fill="currentColor"', svg)
        self.assertIn('stroke="currentColor"', svg)
        self.assertNotIn('fill="#00e868"', svg)            # no colour of its own

    def test_the_stylesheet_shows_one_state_at_a_time(self):
        self.assertIn(".key-eye .eye-open{display:none}", self.body)
        self.assertIn(".key-eye.on .eye-open{display:inline}", self.body)
        self.assertIn(".key-eye.on .eye-shut{display:none}", self.body)

    def test_a_revealed_key_is_hidden_again_when_the_form_leaves(self):
        start = self.body.index('class="key-eye"')
        script = self.body[start:]
        self.assertIn("key.type === 'password'", script)
        self.assertIn("addEventListener('submit'", script)
        self.assertIn("'visibilitychange'", script)


class TheEyeIsOnlyOnTheLoginPageTests(TestCase):
    """"not the pin, the password input"."""

    def setUp(self):
        security._login_attempts.clear()
        user = User.objects.create_user(username="eye_u", password="correct-horse")
        prof = get_or_create_profile(user)
        prof.set_pin("4321")
        prof.save()
        self.client.post("/login/", {"username": "eye_u", "password": "correct-horse"},
                         HTTP_X_REQUESTED_WITH="XMLHttpRequest")

    def test_the_pin_page_has_no_eye(self):
        body = self.client.get("/login/pin/").content.decode()
        self.assertEqual(body.count('class="key-eye"'), 0)
        self.assertNotIn("_key_eye.html", _template("registration/login_pin.html"))

    def test_the_login_page_includes_the_one_partial(self):
        self.assertIn('{% include "registration/_key_eye.html" with target="id_password"',
                      _template("registration/login.html"))
