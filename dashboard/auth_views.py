"""Two-step login: username/password → PIN verification popup."""
from django.contrib import messages
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.hashers import make_password
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator

PENDING_KEY = "sauron_pending_user_id"


def _is_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


@method_decorator(never_cache, name="dispatch")
class SauronLoginView(LoginView):
    template_name = "registration/login.html"

    def get_success_url(self):
        """After login, show the intro loading sequence."""
        return reverse_lazy("intro")

    def form_valid(self, form):
        """Username+password is good → stash user id, send to PIN page."""
        user = form.get_user()
        prof = getattr(user, "trader_profile", None)
        # No PIN configured — full login immediately
        if not prof or not prof.access_pin_hash:
            response = super().form_valid(form)
            if _is_ajax(self.request):
                return JsonResponse({"status": "ok", "redirect": str(self.get_success_url())})
            return response
        # PIN required — stash user id, signal frontend / redirect to PIN page
        self.request.session[PENDING_KEY] = user.id
        self.request.session["sauron_pending_next"] = self.request.POST.get("next") or "/intro/"
        if _is_ajax(self.request):
            return JsonResponse({"status": "pin_required", "username": user.username})
        return redirect("login_pin")

    def form_invalid(self, form):
        if _is_ajax(self.request):
            return JsonResponse({"status": "error", "message": "Invalid credentials"}, status=400)
        return super().form_invalid(form)


@csrf_protect
@never_cache
def login_pin(request):
    from django.contrib.auth.models import User
    uid = request.session.get(PENDING_KEY)
    is_ajax = _is_ajax(request)
    if not uid:
        if is_ajax:
            return JsonResponse({"status": "error", "message": "Session expired"}, status=400)
        return redirect("login")
    try:
        user = User.objects.get(id=uid)
    except User.DoesNotExist:
        request.session.pop(PENDING_KEY, None)
        if is_ajax:
            return JsonResponse({"status": "error", "message": "User not found"}, status=400)
        return redirect("login")

    error = None
    if request.method == "POST":
        # The one PIN check's login step (core/trading_pin.check_login_pin):
        # wrong answers are counted on this pending login, reserved before
        # the hash; the fifth drops the pending login, so the password must
        # be proven again (the IP limiter bounds that). Blank is not counted.
        from core.trading_pin import (LOGIN_ATTEMPTS_KEY, PIN_MISSING,
                                      PIN_WRONG, check_login_pin)
        verdict = check_login_pin(request, user, request.POST.get("pin", ""))
        if verdict.ok:
            auth_login(request, user)
            next_url = request.session.pop("sauron_pending_next", "/intro/") or "/intro/"
            request.session.pop(PENDING_KEY, None)
            # login() keeps the pending session's data: never carry the
            # login step's count into the logged-in session.
            request.session.pop(LOGIN_ATTEMPTS_KEY, None)
            if is_ajax:
                return JsonResponse({"status": "ok", "redirect": next_url})
            return redirect(next_url)
        if verdict.logged_out:
            request.session.pop(PENDING_KEY, None)
            request.session.pop("sauron_pending_next", None)
            error = RESTART
            if is_ajax:
                return JsonResponse({"status": "error", "message": error,
                                     "restart": True}, status=400)
            # Straight back to the password: the PIN pad has nothing left
            # to answer (critique A12).
            messages.error(request, error)
            return redirect("login")
        if verdict.refusal == PIN_MISSING:
            error = "Enter your PIN."
        elif verdict.refusal == PIN_WRONG:
            n = verdict.attempts_left or 0
            error = (f"Invalid PIN: {n} attempt{'' if n == 1 else 's'} left "
                     f"before the password is asked again.")
        else:
            error = "Invalid PIN"
        if is_ajax:
            return JsonResponse({"status": "error", "message": error}, status=400)
    return render(request, "registration/login_pin.html",
                  {"error": error, "username": user.username})


#: The login step's fifth wrong answer: the pending login is dropped.
RESTART = "Too many incorrect PINs: sign in again with your password."


@csrf_protect
@never_cache
def login_pin_forgot(request):
    """Escape hatch for a forgotten PIN. change_pin requires the current PIN
    and login requires the PIN — circular, so a forgotten PIN locked the
    account for good. Re-verify the PENDING user's password (same session
    mechanism as login_pin), complete the login, and flag the session so the
    profile PIN modal waives the current-PIN check exactly once."""
    from django.contrib.auth.models import User
    uid = request.session.get(PENDING_KEY)
    is_ajax = _is_ajax(request)
    if not uid:
        if is_ajax:
            return JsonResponse({"status": "error", "message": "Session expired"}, status=400)
        return redirect("login")
    try:
        user = User.objects.get(id=uid)
    except User.DoesNotExist:
        request.session.pop(PENDING_KEY, None)
        if is_ajax:
            return JsonResponse({"status": "error", "message": "User not found"}, status=400)
        return redirect("login")

    if request.method != "POST":
        return redirect("login_pin")

    password = request.POST.get("password", "")
    if user.check_password(password):
        auth_login(request, user)
        request.session["force_pin_reset"] = True
        request.session.pop(PENDING_KEY, None)
        request.session.pop("sauron_pending_next", None)
        redirect_url = "/profile/?modal=pin"
        if is_ajax:
            return JsonResponse({"status": "ok", "redirect": redirect_url})
        return redirect(redirect_url)
    error = "Password incorrect"
    if is_ajax:
        return JsonResponse({"status": "error", "message": error}, status=400)
    return render(request, "registration/login_pin.html",
                  {"error": error, "username": user.username})
