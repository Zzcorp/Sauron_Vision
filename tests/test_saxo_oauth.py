"""Saxo OAuth: a session that renews itself inside a forty-minute window.

Read off Saxo's developer documentation on 2026-09-17: the access token
lives 1 200 s; the refresh token 2 400 s and ROTATES on every refresh —
"replaces and invalidates the previous refresh token" (developer.saxo,
Security). So the session survives only while the platform keeps
refreshing inside that window — no human needed — and one browser sign-in
is the price of an outage longer than it. These tests hold the numbers, the
request shapes, and the one decision the refresh task makes: transient, or
lost.

WHAT THEY CONFRONT

  * The cadence in config/celery.py against the lifetime in saxo_oauth: a
    beat entry edited alone, or a lifetime corrected alone, fails here.
  * The task against the row: a refresh failure is "retry" while the row's
    refresh_expires_at is ahead of now, "lost" once it is behind — and a
    row that never learned its deadline is lost, not assumed alive.
  * The task against a concurrent run: a lost verdict clears only the row
    still holding the token that failed. A rotation that landed in between
    is kept.
  * The task against the component table: nothing is seeded and the task
    still walks. Ungated by design, named in UNGATED — and the readiness
    report reads the one switch it DOES have, the beat row's enabled box.
  * The views against the session: a callback whose `state` does not match
    stores nothing, whatever code it carries, and consumes the armed state;
    a replay after success is harmless; a state armed by A cannot be
    redeemed by B.
  * Saxo's words against the operator's screen: the JSON error body
    reaches the message and the log, and the redirect-URI hint appears
    only when Saxo names the redirect.
  * The page against the row: five session states, a Connect button that
    follows the session rather than the status flag, and no green on a
    broker nothing can be asked of.
  * Everything against the secrets: no key, token or code in a log line
    or a rendered page.
"""
import base64
from datetime import timedelta
from unittest import mock
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from bot_program import campaign_readiness as pr
from bot_program.engine import saxo_oauth
from bot_program.engine.saxo_oauth import SaxoTokenError
from bot_program.models import EtoroAccount, SaxoAccount
from bot_program.tasks import refresh_saxo_sessions
from dashboard.views_brokers import SAXO_STATE_KEY

RAW_APP = "saxo-app-0c1d2e"
RAW_SECRET = "saxo-secret-3f4a5b"
REDIRECT = "https://sauron.example.net/brokers/saxo/callback/"
TASK = "bot_program.tasks.refresh_saxo_sessions"
SECRETS = (RAW_APP, RAW_SECRET, "acc-old", "ref-old", "acc-new", "ref-new")

TOKENS = {"access_token": "acc-new", "refresh_token": "ref-new",
          "expires_in": 1200, "refresh_token_expires_in": 2400}


def registered(user, sim=True, redirect=REDIRECT):
    acct = SaxoAccount.objects.create(user=user, sim=sim, redirect_uri=redirect)
    acct.set_credentials(RAW_APP, RAW_SECRET)
    acct.save()
    return acct


def with_session(acct, refresh_deadline, now=None, access_deadline=None):
    now = now or timezone.now()
    acct.set_tokens("acc-old", "ref-old",
                    access_deadline or now + timedelta(seconds=1200),
                    refresh_expires_at=refresh_deadline)
    acct.connected = True
    acct.save()
    return acct


def ahead(seconds=2400):
    return timezone.now() + timedelta(seconds=seconds)


def behind(seconds=1):
    return timezone.now() - timedelta(seconds=seconds)


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._payload is None:
            raise ValueError("not JSON")
        return self._payload


class FakeSession:
    """Records the one POST the token endpoint sees."""

    def __init__(self, status=200, payload=None):
        self.calls = []
        self.response = FakeResponse(status, payload if payload is not None
                                     else {})

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers,
                           "timeout": timeout})
        return self.response


class TheNumbersTests(TestCase):

    def test_the_fallback_lifetimes_are_the_documented_examples(self):
        """The response's own numbers are authoritative; these stand in
        only when Saxo omits them."""
        self.assertEqual(saxo_oauth.ACCESS_TOKEN_SECONDS, 1200)
        self.assertEqual(saxo_oauth.REFRESH_TOKEN_SECONDS, 2400)

    def test_cadence_leaves_room_for_two_missed_cycles(self):
        """Two consecutive missed beats and the third still lands strictly
        before the refresh token dies: 3 × cadence < lifetime."""
        self.assertLess(3 * saxo_oauth.REFRESH_EVERY_S,
                        saxo_oauth.REFRESH_TOKEN_SECONDS)

    def test_beat_entry_matches_the_module_cadence_and_expires(self):
        from config.celery import app
        entry = app.conf.beat_schedule.get("refresh-saxo-sessions")
        self.assertIsNotNone(entry, "beat entry missing")
        self.assertEqual(entry["task"], TASK)
        self.assertEqual(entry["schedule"], saxo_oauth.REFRESH_EVERY_S)
        # A backlog must never drain two rotations at once.
        self.assertLess(entry["options"]["expires"], saxo_oauth.REFRESH_EVERY_S)

    def test_named_among_the_ungated_at_the_same_cadence(self):
        every = {task: secs for task, secs, _why in pr.UNGATED}
        self.assertIn(TASK, every)
        self.assertEqual(every[TASK], saxo_oauth.REFRESH_EVERY_S)

    def test_sim_and_live_are_different_worlds(self):
        self.assertNotEqual(saxo_oauth.AUTH_HOST["sim"],
                            saxo_oauth.AUTH_HOST["live"])
        self.assertIn("/sim/", saxo_oauth.API_BASE["sim"])
        self.assertNotIn("/sim/", saxo_oauth.API_BASE["live"])
        self.assertIn("/sim/", saxo_oauth.STREAM_BASE["sim"])
        self.assertNotIn("/sim/", saxo_oauth.STREAM_BASE["live"])


class TheRowTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_row_u", password="x")

    def test_env_follows_the_sim_flag(self):
        self.assertEqual(saxo_oauth.env_of(SaxoAccount(user=self.user, sim=True)),
                         "sim")
        self.assertEqual(saxo_oauth.env_of(SaxoAccount(user=self.user, sim=False)),
                         "live")

    def test_clear_session_leaves_registered_but_not_connected(self):
        acct = registered(self.user)
        with_session(acct, ahead())
        self.assertTrue(acct.has_session)
        acct.clear_session()
        acct.save()
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertFalse(stored.has_session)
        self.assertFalse(stored.connected)
        self.assertIsNone(stored.token_expires_at)
        self.assertIsNone(stored.refresh_expires_at)
        self.assertIsNone(stored.get_access_token())
        self.assertIsNone(stored.get_refresh_token())
        # the application survives: it never expires
        self.assertEqual(stored.get_credentials(), (RAW_APP, RAW_SECRET))

    def test_session_alive_reads_the_refresh_deadline(self):
        acct = registered(self.user)
        self.assertFalse(acct.session_alive())
        with_session(acct, ahead())
        self.assertTrue(acct.session_alive())
        with_session(acct, behind())
        self.assertFalse(acct.session_alive())
        # unknown deadline: alive until the keeper says otherwise
        with_session(acct, None)
        self.assertTrue(acct.session_alive())

    def test_access_token_valid_keeps_a_margin(self):
        acct = registered(self.user)
        self.assertFalse(acct.access_token_valid())
        with_session(acct, ahead(), access_deadline=ahead(1200))
        self.assertTrue(acct.access_token_valid())
        with_session(acct, ahead(), access_deadline=ahead(30))
        self.assertFalse(acct.access_token_valid(margin_s=60))
        self.assertTrue(acct.access_token_valid(margin_s=10))
        with_session(acct, ahead(), access_deadline=behind())
        self.assertFalse(acct.access_token_valid())

    def test_mark_session_lost_records_when_and_why(self):
        acct = registered(self.user)
        with_session(acct, behind())
        acct.mark_session_lost("SaxoTokenError: HTTP 401 invalid_grant " + "x" * 200)
        acct.save()
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertFalse(stored.has_session)
        self.assertIsNotNone(stored.session_lost_at)
        self.assertEqual(len(stored.session_lost_reason), 120)
        self.assertTrue(stored.session_lost_reason.startswith("SaxoTokenError"))


class TheAuthorizeUrlTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_auth_u", password="x")

    def test_sim_row_goes_to_the_sim_host_with_the_registered_uri(self):
        acct = registered(self.user, sim=True)
        url = saxo_oauth.authorize_url(acct, "state-abc")
        parts = urlparse(url)
        self.assertEqual(f"{parts.scheme}://{parts.netloc}",
                         saxo_oauth.AUTH_HOST["sim"])
        self.assertEqual(parts.path, "/authorize")
        q = parse_qs(parts.query)
        self.assertEqual(q["response_type"], ["code"])
        self.assertEqual(q["client_id"], [RAW_APP])
        self.assertEqual(q["redirect_uri"], [REDIRECT])
        self.assertEqual(q["state"], ["state-abc"])
        self.assertNotIn(RAW_SECRET, url)

    def test_live_row_goes_to_the_live_host(self):
        acct = registered(self.user, sim=False)
        self.assertTrue(saxo_oauth.authorize_url(acct, "s").startswith(
            saxo_oauth.AUTH_HOST["live"] + "/authorize?"))

    def test_unregistered_row_refuses(self):
        bare = SaxoAccount.objects.create(user=self.user, redirect_uri=REDIRECT)
        with self.assertRaises(ValueError):
            saxo_oauth.authorize_url(bare, "s")
        no_uri = registered(User.objects.create_user("saxo_auth_u2", password="x"),
                            redirect="")
        with self.assertRaises(ValueError):
            saxo_oauth.authorize_url(no_uri, "s")


class TheTokenPostTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_tok_u", password="x")
        self.acct = registered(self.user)

    def test_exchange_code_is_basic_auth_form_encoded_on_the_env_host(self):
        sess = FakeSession(200, TOKENS)
        out = saxo_oauth.exchange_code(self.acct, "the-code", session=sess)
        self.assertEqual(out, TOKENS)
        call = sess.calls[0]
        self.assertEqual(call["url"], saxo_oauth.AUTH_HOST["sim"] + "/token")
        basic = base64.b64encode(f"{RAW_APP}:{RAW_SECRET}".encode()).decode()
        self.assertEqual(call["headers"]["Authorization"], f"Basic {basic}")
        self.assertEqual(call["headers"]["Content-Type"],
                         "application/x-www-form-urlencoded")
        self.assertEqual(call["data"], {"grant_type": "authorization_code",
                                        "code": "the-code",
                                        "redirect_uri": REDIRECT})
        self.assertIsNotNone(call["timeout"])

    def test_live_row_posts_to_the_live_host(self):
        acct = registered(User.objects.create_user("saxo_tok_u2", password="x"),
                          sim=False)
        sess = FakeSession(200, TOKENS)
        saxo_oauth.exchange_code(acct, "c", session=sess)
        self.assertEqual(sess.calls[0]["url"],
                         saxo_oauth.AUTH_HOST["live"] + "/token")

    def test_refresh_sends_the_current_refresh_token(self):
        with_session(self.acct, ahead())
        sess = FakeSession(200, TOKENS)
        saxo_oauth.refresh(self.acct, session=sess)
        self.assertEqual(sess.calls[0]["data"], {"grant_type": "refresh_token",
                                                 "refresh_token": "ref-old"})

    def test_refresh_without_a_session_refuses_before_any_request(self):
        sess = FakeSession(200, TOKENS)
        with self.assertRaises(ValueError):
            saxo_oauth.refresh(self.acct, session=sess)
        self.assertEqual(sess.calls, [])

    def test_a_refused_post_raises_and_stores_nothing(self):
        sess = FakeSession(401, {"error": "invalid_client"})
        with self.assertRaises(RuntimeError):
            saxo_oauth.exchange_code(self.acct, "bad", session=sess)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_refusal_carries_saxos_own_words_and_nothing_of_ours(self):
        """invalid_client, invalid_grant and a redirect mismatch are told
        apart only by the JSON body; requests' HTTPError text drops it."""
        sess = FakeSession(400, {"error": "invalid_grant",
                                 "error_description": "Refresh token has expired"})
        with self.assertRaises(SaxoTokenError) as cm:
            saxo_oauth.exchange_code(self.acct, "code-7f3e9a", session=sess)
        msg = str(cm.exception)
        self.assertIn("400", msg)
        self.assertIn("invalid_grant", msg)
        self.assertIn("Refresh token has expired", msg)
        self.assertNotIn("code-7f3e9a", msg)
        for s in SECRETS:
            self.assertNotIn(s, msg)

    def test_a_refusal_without_a_json_body_still_names_the_status(self):
        sess = FakeSession(503, None)
        with self.assertRaises(SaxoTokenError) as cm:
            saxo_oauth.refresh(with_session(self.acct, ahead()), session=sess)
        self.assertIn("503", str(cm.exception))


class StoreTokensTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_store_u", password="x")
        self.acct = registered(self.user)

    def test_both_deadlines_land_and_the_row_is_connected(self):
        now = timezone.now()
        saxo_oauth.store_tokens(self.acct, TOKENS, now=now)
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(stored.get_access_token(), "acc-new")
        self.assertEqual(stored.get_refresh_token(), "ref-new")
        self.assertEqual(stored.token_expires_at, now + timedelta(seconds=1200))
        self.assertEqual(stored.refresh_expires_at, now + timedelta(seconds=2400))
        self.assertTrue(stored.connected)
        self.assertEqual(stored.last_sync, now)
        self.assertNotIn("acc-new", stored.access_token_enc)
        self.assertNotIn("ref-new", stored.refresh_token_enc)

    def test_the_response_lifetimes_win_over_the_fallbacks(self):
        now = timezone.now()
        saxo_oauth.store_tokens(self.acct, dict(TOKENS, expires_in=900,
                                                refresh_token_expires_in=3600),
                                now=now)
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(stored.token_expires_at, now + timedelta(seconds=900))
        self.assertEqual(stored.refresh_expires_at, now + timedelta(seconds=3600))

    def test_omitted_refresh_lifetime_falls_back_to_the_documented_one(self):
        """Saxo may omit refresh_token_expires_in; the row must still carry
        a deadline the task can read, or every failure would read as lost."""
        now = timezone.now()
        saxo_oauth.store_tokens(self.acct, {"access_token": "a",
                                            "refresh_token": "r"}, now=now)
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(stored.refresh_expires_at, now + timedelta(
            seconds=saxo_oauth.REFRESH_TOKEN_SECONDS))
        self.assertEqual(stored.token_expires_at, now + timedelta(
            seconds=saxo_oauth.ACCESS_TOKEN_SECONDS))

    def test_a_response_without_the_pair_stores_nothing(self):
        with self.assertRaises(ValueError):
            saxo_oauth.store_tokens(self.acct, {"access_token": "a"})
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_new_session_clears_the_record_of_the_lost_one(self):
        self.acct.mark_session_lost("HTTP 401 invalid_grant")
        self.acct.save()
        saxo_oauth.store_tokens(self.acct, TOKENS)
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertIsNone(stored.session_lost_at)
        self.assertEqual(stored.session_lost_reason, "")


class EnsureAccessTokenTests(TestCase):
    """The adapter's entry point: never hands out a bearer Saxo will 401."""

    def setUp(self):
        self.user = User.objects.create_user("saxo_ens_u", password="x")
        self.acct = registered(self.user)

    def test_a_valid_token_is_returned_without_a_request(self):
        with_session(self.acct, ahead(), access_deadline=ahead(1200))
        sess = FakeSession(200, TOKENS)
        self.assertEqual(saxo_oauth.ensure_access_token(self.acct, session=sess),
                         "acc-old")
        self.assertEqual(sess.calls, [])

    def test_a_dead_access_token_on_a_live_session_rotates_once(self):
        with_session(self.acct, ahead(), access_deadline=behind())
        sess = FakeSession(200, TOKENS)
        self.assertEqual(saxo_oauth.ensure_access_token(self.acct, session=sess),
                         "acc-new")
        self.assertEqual(len(sess.calls), 1)
        self.assertEqual(sess.calls[0]["data"]["grant_type"], "refresh_token")
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(stored.get_refresh_token(), "ref-new")

    def test_a_dead_session_refuses_without_a_request(self):
        with_session(self.acct, behind(), access_deadline=behind())
        sess = FakeSession(200, TOKENS)
        with self.assertRaises(SaxoTokenError) as cm:
            saxo_oauth.ensure_access_token(self.acct, session=sess)
        self.assertIn("sign in again", str(cm.exception))
        self.assertEqual(sess.calls, [])
        self.assertEqual(SaxoAccount.objects.get(pk=self.acct.pk).get_refresh_token(),
                         "ref-old")


class RefreshTaskTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_task_u", password="x")
        self.acct = registered(self.user)

    def test_nothing_seeded_and_it_still_walks(self):
        """Ungated: no PlatformComponent row is seeded here, and the row is
        attempted. A guarded task with a missing row returns without
        touching anything."""
        with_session(self.acct, ahead())
        with mock.patch.object(saxo_oauth, "refresh", return_value=TOKENS):
            out = refresh_saxo_sessions()
        self.assertEqual(out["attempted"], 1)
        self.assertEqual(out["renewed"], 1)

    def test_a_renewal_rotates_both_tokens_and_advances_both_deadlines(self):
        old_deadline = ahead(600)
        with_session(self.acct, old_deadline)
        with mock.patch.object(saxo_oauth, "refresh", return_value=TOKENS) as ref:
            out = refresh_saxo_sessions()
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(out, {"attempted": 1, "renewed": 1, "lost": 0, "retry": 0})
        self.assertEqual(stored.get_refresh_token(), "ref-new")
        self.assertEqual(stored.get_access_token(), "acc-new")
        self.assertGreater(stored.refresh_expires_at, old_deadline)
        self.assertTrue(stored.connected)
        ref.assert_called_once()

    def test_a_failure_inside_the_window_keeps_the_session(self):
        deadline = ahead(1500)
        with_session(self.acct, deadline)
        with mock.patch.object(saxo_oauth, "refresh",
                               side_effect=SaxoTokenError("HTTP 503")):
            with mock.patch("bot_program.notifications.notify_staff") as notify:
                with self.assertLogs("bot_program.tasks", level="WARNING") as cm:
                    out = refresh_saxo_sessions()
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(out["retry"], 1)
        self.assertEqual(out["lost"], 0)
        self.assertTrue(stored.has_session)
        self.assertTrue(stored.connected)
        self.assertEqual(stored.get_refresh_token(), "ref-old")
        self.assertEqual(stored.refresh_expires_at, deadline)
        self.assertIsNone(stored.session_lost_at)
        self.assertTrue(any("retrying next cycle" in m for m in cm.output))
        notify.assert_not_called()
        for s in SECRETS:
            self.assertNotIn(s, "".join(cm.output))

    def test_a_failure_past_the_deadline_is_a_lost_session_and_staff_hear(self):
        with_session(self.acct, behind())
        with mock.patch.object(saxo_oauth, "refresh",
                               side_effect=SaxoTokenError(
                                   "HTTP 401 invalid_grant: token dead")):
            with mock.patch("bot_program.notifications.notify_staff") as notify:
                with self.assertLogs("bot_program.tasks", level="WARNING") as cm:
                    out = refresh_saxo_sessions()
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(out["lost"], 1)
        self.assertEqual(out["retry"], 0)
        self.assertFalse(stored.has_session)
        self.assertFalse(stored.connected)
        self.assertIsNone(stored.refresh_expires_at)
        self.assertIsNotNone(stored.session_lost_at)
        self.assertIn("invalid_grant", stored.session_lost_reason)
        # the application survives a lost session
        self.assertEqual(stored.get_credentials(), (RAW_APP, RAW_SECRET))
        self.assertTrue(any("LOST" in m and "Sign in again" in m
                            for m in cm.output))
        for s in SECRETS:
            self.assertNotIn(s, "".join(cm.output))
        notify.assert_called_once()
        kw = notify.call_args.kwargs
        self.assertIn("sign in again", kw["title"])
        self.assertEqual(kw["url"], "/brokers/")
        for s in SECRETS:
            self.assertNotIn(s, kw["title"] + kw["body"])

    def test_an_alert_failure_never_fails_the_keeper(self):
        with_session(self.acct, behind())
        with mock.patch.object(saxo_oauth, "refresh",
                               side_effect=SaxoTokenError("HTTP 401")):
            with mock.patch("bot_program.notifications.notify_staff",
                            side_effect=RuntimeError("mail is down")):
                with self.assertLogs("bot_program.tasks", level="WARNING"):
                    out = refresh_saxo_sessions()
        self.assertEqual(out["lost"], 1)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_row_that_never_learned_its_deadline_is_not_assumed_alive(self):
        """Unmeasured is not alive: a token with no known deadline that
        fails to refresh is lost, not retried on faith."""
        with_session(self.acct, None)
        with mock.patch.object(saxo_oauth, "refresh", side_effect=RuntimeError("x")):
            with mock.patch("bot_program.notifications.notify_staff"):
                with self.assertLogs("bot_program.tasks", level="WARNING"):
                    out = refresh_saxo_sessions()
        self.assertEqual(out["lost"], 1)
        self.assertEqual(out["retry"], 0)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_2xx_without_the_pair_is_judged_by_the_row(self):
        """A response store_tokens rejects is a failure like any other: the
        row's deadline decides, and the old tokens are untouched."""
        with_session(self.acct, ahead())
        with mock.patch.object(saxo_oauth, "refresh",
                               return_value={"access_token": "a"}):
            with self.assertLogs("bot_program.tasks", level="WARNING"):
                out = refresh_saxo_sessions()
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(out["retry"], 1)
        self.assertEqual(stored.get_refresh_token(), "ref-old")
        self.assertTrue(stored.has_session)

    def test_a_row_rotated_by_another_run_is_not_cleared(self):
        """Compare-and-clear: run B fails on a token run A already replaced.
        B must not wipe A's fresh session."""
        with_session(self.acct, behind())

        def refresh(acct, session=None):
            other = SaxoAccount.objects.get(pk=acct.pk)   # run A, in between
            other.set_tokens("acc-2", "ref-2", ahead(1200), refresh_expires_at=ahead())
            other.save()
            raise SaxoTokenError("HTTP 401 invalid_grant")

        with mock.patch.object(saxo_oauth, "refresh", side_effect=refresh):
            with mock.patch("bot_program.notifications.notify_staff") as notify:
                out = refresh_saxo_sessions()
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertEqual(out["lost"], 0)
        self.assertEqual(stored.get_refresh_token(), "ref-2")
        self.assertTrue(stored.connected)
        self.assertIsNone(stored.session_lost_at)
        notify.assert_not_called()

    def test_a_registered_row_without_a_session_is_not_attempted(self):
        with mock.patch.object(saxo_oauth, "refresh") as ref:
            out = refresh_saxo_sessions()
        self.assertEqual(out["attempted"], 0)
        ref.assert_not_called()

    def test_one_lost_row_does_not_stop_the_next(self):
        other = registered(User.objects.create_user("saxo_task_u2", password="x"))
        with_session(self.acct, behind())
        with_session(other, ahead())

        def refresh(acct, session=None):
            if acct.pk == self.acct.pk:
                raise SaxoTokenError("HTTP 401")
            return TOKENS

        with mock.patch.object(saxo_oauth, "refresh", side_effect=refresh):
            with mock.patch("bot_program.notifications.notify_staff"):
                with self.assertLogs("bot_program.tasks", level="WARNING"):
                    out = refresh_saxo_sessions()
        self.assertEqual(out["attempted"], 2)
        self.assertEqual(out["lost"], 1)
        self.assertEqual(out["renewed"], 1)
        self.assertEqual(SaxoAccount.objects.get(pk=other.pk).get_refresh_token(),
                         "ref-new")


class ReadinessKnowsTheBeatSwitchTests(TestCase):
    """'Ungated' is true of PlatformComponent, not of the DatabaseScheduler's
    PeriodicTask.enabled box, which stays unticked across restarts."""

    def _row(self, enabled):
        from django_celery_beat.models import IntervalSchedule, PeriodicTask
        every = IntervalSchedule.objects.create(every=600,
                                                period=IntervalSchedule.SECONDS)
        return PeriodicTask.objects.create(name="refresh-saxo-sessions",
                                           task=TASK, interval=every,
                                           enabled=enabled)

    def test_a_disabled_beat_row_is_a_blocker_that_names_the_task(self):
        self._row(enabled=False)
        blockers = pr.readiness()["blockers"]
        self.assertTrue(any("refresh_saxo_sessions" in b and "DISABLED" in b
                            for b in blockers), blockers)

    def test_an_enabled_row_is_not(self):
        self._row(enabled=True)
        blockers = pr.readiness()["blockers"]
        self.assertFalse(any("refresh_saxo_sessions" in b for b in blockers),
                         blockers)


class ConnectViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_view_u", password="x")

    def test_anonymous_is_not_sent_to_saxo(self):
        r = self.client.get(reverse("saxo_connect"))
        self.assertNotEqual(r.status_code, 200)
        self.assertNotIn("logonvalidation", r.get("Location", ""))

    def test_unregistered_row_gets_a_message_not_saxo(self):
        SaxoAccount.objects.create(user=self.user)
        self.client.login(username="saxo_view_u", password="x")
        r = self.client.get(reverse("saxo_connect"))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r["Location"], reverse("brokers_page"))
        self.assertNotIn(SAXO_STATE_KEY, self.client.session)

    def test_registered_row_is_sent_to_saxo_with_a_state_in_the_session(self):
        registered(self.user)
        self.client.login(username="saxo_view_u", password="x")
        r = self.client.get(reverse("saxo_connect"))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r["Location"].startswith(
            saxo_oauth.AUTH_HOST["sim"] + "/authorize?"))
        state = self.client.session.get(SAXO_STATE_KEY)
        self.assertTrue(state)
        self.assertEqual(parse_qs(urlparse(r["Location"]).query)["state"],
                         [state])

    def test_a_wrong_redirect_path_arms_nothing(self):
        """A URI landing anywhere but the callback would make the sign-in a
        silent no-op with the state left dangling."""
        registered(self.user, redirect="https://sauron.example.net/brokers/")
        self.client.login(username="saxo_view_u", password="x")
        r = self.client.get(reverse("saxo_connect"), follow=True)
        self.assertNotIn(SAXO_STATE_KEY, self.client.session)
        self.assertContains(r, "redirect URI")


class CallbackViewTests(TestCase):

    def setUp(self):
        self.user = User.objects.create_user("saxo_cb_u", password="x")
        self.acct = registered(self.user)
        self.client.login(username="saxo_cb_u", password="x")

    def _arm(self, state, client=None):
        s = (client or self.client).session
        s[SAXO_STATE_KEY] = state
        s.save()

    def test_a_mismatched_state_stores_nothing_whatever_the_code(self):
        self._arm("expected")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            r = self.client.get(reverse("saxo_callback"),
                                {"code": "c", "state": "forged"})
        self.assertEqual(r["Location"], reverse("brokers_page"))
        ex.assert_not_called()
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)
        # the armed state is consumed: a second forged try cannot reuse it
        self.assertNotIn(SAXO_STATE_KEY, self.client.session)

    def test_no_armed_state_at_all_stores_nothing(self):
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            r = self.client.get(reverse("saxo_callback"),
                                {"code": "c", "state": "any"}, follow=True)
        ex.assert_not_called()
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)
        self.assertContains(r, "nothing was stored")

    def test_no_row_at_all_stores_nothing_and_says_so(self):
        lone = User.objects.create_user("saxo_cb_lone", password="x")
        c = Client()
        c.login(username="saxo_cb_lone", password="x")
        self._arm("s0", client=c)
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            r = c.get(reverse("saxo_callback"), {"code": "c", "state": "s0"},
                      follow=True)
        ex.assert_not_called()
        self.assertContains(r, "no application registered")
        self.assertFalse(SaxoAccount.objects.filter(user=lone).exists())

    def test_a_matching_state_exchanges_the_code_and_opens_the_session(self):
        self._arm("s1")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            r = self.client.get(reverse("saxo_callback"),
                                {"code": "the-code", "state": "s1"}, follow=True)
        ex.assert_called_once()
        self.assertEqual(ex.call_args.args[1], "the-code")
        stored = SaxoAccount.objects.get(pk=self.acct.pk)
        self.assertTrue(stored.has_session)
        self.assertTrue(stored.connected)
        self.assertEqual(stored.get_refresh_token(), "ref-new")
        self.assertIsNotNone(stored.refresh_expires_at)
        self.assertContains(r, "Saxo session opened")

    def test_a_replayed_callback_is_harmless(self):
        """F5 after success: the state is spent, the session is open, and
        the operator is not told to start again."""
        self._arm("s1")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            first = self.client.get(reverse("saxo_callback"),
                                    {"code": "the-code", "state": "s1"},
                                    follow=True)
            again = self.client.get(reverse("saxo_callback"),
                                    {"code": "the-code", "state": "s1"},
                                    follow=True)
        ex.assert_called_once()
        self.assertContains(first, "Saxo session opened")
        self.assertContains(again, "already open")
        self.assertNotContains(again, "nothing was stored")
        self.assertTrue(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_the_callback_lands_on_the_requesting_users_row_only(self):
        other = User.objects.create_user("saxo_cb_b", password="x")
        registered(other)
        c = Client()
        c.login(username="saxo_cb_b", password="x")
        self._arm("sb", client=c)
        with mock.patch.object(saxo_oauth, "exchange_code", return_value=TOKENS):
            c.get(reverse("saxo_callback"), {"code": "cb", "state": "sb"})
        self.assertTrue(SaxoAccount.objects.get(user=other).has_session)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_state_armed_by_a_cannot_be_redeemed_by_b(self):
        other = User.objects.create_user("saxo_cb_b2", password="x")
        registered(other)
        self._arm("sa")                                    # A's session
        c = Client()
        c.login(username="saxo_cb_b2", password="x")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               return_value=TOKENS) as ex:
            c.get(reverse("saxo_callback"), {"code": "c", "state": "sa"})
        ex.assert_not_called()
        self.assertFalse(SaxoAccount.objects.get(user=other).has_session)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)

    def test_a_failed_exchange_says_so_renders_no_secret_and_no_false_hint(self):
        self._arm("s2")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               side_effect=SaxoTokenError(
                                   "HTTP 401 invalid_client: bad secret")):
            r = self.client.get(reverse("saxo_callback"),
                                {"code": "code-7f3e9a", "state": "s2"},
                                follow=True)
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)
        self.assertContains(r, "code exchange failed")
        self.assertContains(r, "invalid_client")
        self.assertNotContains(r, "must match the portal")
        page = r.content.decode()
        self.assertNotIn("code-7f3e9a", page)
        for s in SECRETS:
            self.assertNotIn(s, page)

    def test_the_redirect_hint_appears_only_when_saxo_names_the_redirect(self):
        self._arm("s3")
        with mock.patch.object(saxo_oauth, "exchange_code",
                               side_effect=SaxoTokenError(
                                   "HTTP 400 invalid_request: redirect_uri mismatch")):
            r = self.client.get(reverse("saxo_callback"),
                                {"code": "c", "state": "s3"}, follow=True)
        self.assertContains(r, "must match the portal")

    def test_no_code_reports_saxo_error_and_stores_nothing(self):
        self._arm("s4")
        r = self.client.get(reverse("saxo_callback"),
                            {"state": "s4", "error": "access_denied"}, follow=True)
        self.assertContains(r, "access_denied")
        self.assertFalse(SaxoAccount.objects.get(pk=self.acct.pk).has_session)


class TheSaveViewTests(TestCase):
    """Registering is superuser + POST; a session belongs to one
    application on one environment."""

    def setUp(self):
        self.admin = User.objects.create_superuser("saxo_save_admin", "a@x", "x")
        self.client.login(username="saxo_save_admin", password="x")

    def _post(self, **over):
        data = {"target_username": self.admin.username,
                "saxo_app_key": "k2", "saxo_app_secret": "s2",
                "saxo_redirect_uri": REDIRECT, "sim": "on"}
        data.update(over)
        return self.client.post(reverse("hq_save_saxo"), data, follow=True)

    def test_a_resave_closes_the_open_session_and_offers_connect(self):
        acct = registered(self.admin)
        with_session(acct, ahead())
        r = self._post(sim="")
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertFalse(stored.has_session)
        self.assertFalse(stored.connected)
        self.assertFalse(stored.sim)
        self.assertEqual(stored.get_credentials(), ("k2", "s2"))
        self.assertContains(r, "Not yet")
        self.assertContains(r, "Connect Saxo")
        self.assertContains(r, reverse("saxo_connect"))
        self.assertNotContains(r, "session: renewable")

    def test_a_wrong_path_is_refused_and_nothing_is_saved(self):
        r = self._post(saxo_redirect_uri="https://sauron.example.net/brokers/")
        self.assertFalse(SaxoAccount.objects.filter(user=self.admin).exists())
        self.assertContains(r, "redirect URI")
        self.assertContains(r, reverse("saxo_callback"))

    def test_http_is_refused_except_for_localhost(self):
        self._post(saxo_redirect_uri="http://sauron.example.net/brokers/saxo/callback/")
        self.assertFalse(SaxoAccount.objects.filter(user=self.admin).exists())
        self._post(saxo_redirect_uri="http://localhost:8000/brokers/saxo/callback/")
        self.assertTrue(SaxoAccount.objects.filter(user=self.admin).exists())


class ForgetTests(TestCase):
    """The house pattern for pulling a broker's secrets, extended to the
    two rows that had none."""

    def setUp(self):
        self.admin = User.objects.create_superuser("saxo_forget_admin", "a@x", "x")
        self.plain = User.objects.create_user("saxo_forget_plain", password="x")

    def test_superuser_forgets_saxo_keys_and_session(self):
        acct = with_session(registered(self.admin), ahead())
        self.client.login(username="saxo_forget_admin", password="x")
        r = self.client.post(reverse("hq_disconnect_saxo"),
                             {"target_username": self.admin.username}, follow=True)
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertEqual(stored.get_credentials(), (None, None))
        self.assertFalse(stored.has_session)
        self.assertFalse(stored.connected)
        self.assertContains(r, "forgotten")
        with mock.patch.object(saxo_oauth, "refresh") as ref:
            self.assertEqual(refresh_saxo_sessions()["attempted"], 0)
        ref.assert_not_called()
        self.assertNotContains(r, reverse("saxo_connect"))

    def test_superuser_forgets_etoro_keys(self):
        acct = EtoroAccount.objects.create(user=self.admin)
        acct.set_credentials("etoro-key-9f3a", "etoro-user-b81e")
        acct.save()
        self.client.login(username="saxo_forget_admin", password="x")
        self.client.post(reverse("hq_disconnect_etoro"),
                         {"target_username": self.admin.username})
        self.assertEqual(EtoroAccount.objects.get(pk=acct.pk).get_credentials(),
                         (None, None))

    def test_a_plain_user_cannot_forget_anyone(self):
        acct = with_session(registered(self.plain), ahead())
        self.client.login(username="saxo_forget_plain", password="x")
        self.client.post(reverse("hq_disconnect_saxo"),
                         {"target_username": self.plain.username})
        stored = SaxoAccount.objects.get(pk=acct.pk)
        self.assertTrue(stored.has_session)
        self.assertEqual(stored.get_credentials(), (RAW_APP, RAW_SECRET))


class ThePageTests(TestCase):
    """Five session states, and no green on a broker nothing can be asked
    of."""

    def setUp(self):
        self.user = User.objects.create_user("saxo_page_u", password="x")
        self.client.login(username="saxo_page_u", password="x")

    def _page(self):
        return self.client.get(reverse("brokers_page"))

    def test_registered_without_a_session_shows_connect(self):
        registered(self.user)
        r = self._page()
        self.assertContains(r, reverse("saxo_connect"))
        self.assertContains(r, "not yet done")

    def test_with_a_live_session_the_button_is_gone_and_the_row_is_green(self):
        """Green means "can be asked of". Until 2026-09-19 that was false for
        Saxo whatever its session said, and the row read "adapter pending";
        the adapter landed, so a signed-in row is now green — and the page
        said otherwise for three days after."""
        with_session(registered(self.user), ahead())
        r = self._page()
        self.assertNotContains(r, reverse("saxo_connect"))
        self.assertContains(r, "session: renewable")
        self.assertNotContains(r, "adapter pending")

    def test_unregistered_shows_no_connect(self):
        SaxoAccount.objects.create(user=self.user)
        self.assertNotContains(self._page(), reverse("saxo_connect"))

    def test_a_lost_session_says_so_and_offers_connect(self):
        acct = registered(self.user)
        acct.mark_session_lost("SaxoTokenError: HTTP 401 invalid_grant")
        acct.save()
        r = self._page()
        self.assertContains(r, "LOST")
        self.assertContains(r, "sign in again")
        self.assertContains(r, "invalid_grant")
        self.assertContains(r, reverse("saxo_connect"))
        self.assertNotContains(r, "not yet done")

    def test_an_expired_session_offers_connect(self):
        with_session(registered(self.user), behind())
        r = self._page()
        self.assertContains(r, "EXPIRED")
        self.assertContains(r, reverse("saxo_connect"))

    def test_a_dead_access_token_on_a_live_session_is_renewing_not_a_signin(self):
        with_session(registered(self.user), ahead(), access_deadline=behind())
        r = self._page()
        self.assertContains(r, "renewing")
        self.assertNotContains(r, reverse("saxo_connect"))

    def test_a_plain_user_sees_no_forget_button(self):
        with_session(registered(self.user), ahead())
        self.assertNotContains(self._page(), reverse("hq_disconnect_saxo"))

    def test_a_superuser_sees_the_forget_button(self):
        admin = User.objects.create_superuser("saxo_page_admin", "a@x", "x")
        with_session(registered(admin), ahead())
        self.client.login(username="saxo_page_admin", password="x")
        self.assertContains(self._page(), reverse("hq_disconnect_saxo"))
