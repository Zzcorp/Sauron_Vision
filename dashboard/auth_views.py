"""Two-step login: username/password → PIN verification popup."""
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.hashers import check_password, make_password
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
        pin = request.POST.get("pin", "")
        prof = getattr(user, "trader_profile", None)
        if prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash):
            auth_login(request, user)
            next_url = request.session.pop("sauron_pending_next", "/intro/") or "/intro/"
            request.session.pop(PENDING_KEY, None)
            if is_ajax:
                return JsonResponse({"status": "ok", "redirect": next_url})
            return redirect(next_url)
        error = "Invalid PIN"
        if is_ajax:
            return JsonResponse({"status": "error", "message": error}, status=400)
    return render(request, "registration/login_pin.html",
                  {"error": error, "username": user.username})
