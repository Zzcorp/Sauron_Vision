"""Two-step login: username/password → PIN verification popup."""
from django.contrib.auth import authenticate, login as auth_login
from django.contrib.auth.hashers import check_password, make_password
from django.shortcuts import render, redirect
from django.contrib.auth.views import LoginView
from django.urls import reverse_lazy
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator

PENDING_KEY = "sauron_pending_user_id"

@method_decorator(never_cache, name="dispatch")
class SauronLoginView(LoginView):
    template_name = "registration/login.html"

    def form_valid(self, form):
        """Username+password is good → stash user id, send to PIN page."""
        user = form.get_user()
        # If user has no PIN set, just log in normally.
        prof = getattr(user, "trader_profile", None)
        if not prof or not prof.access_pin_hash:
            return super().form_valid(form)
        self.request.session[PENDING_KEY] = user.id
        self.request.session["sauron_pending_next"] = self.request.POST.get("next") or "/"
        return redirect("login_pin")


@csrf_protect
@never_cache
def login_pin(request):
    from django.contrib.auth.models import User
    uid = request.session.get(PENDING_KEY)
    if not uid:
        return redirect("login")
    try:
        user = User.objects.get(id=uid)
    except User.DoesNotExist:
        request.session.pop(PENDING_KEY, None)
        return redirect("login")

    error = None
    if request.method == "POST":
        pin = request.POST.get("pin", "")
        prof = getattr(user, "trader_profile", None)
        if prof and prof.access_pin_hash and check_password(pin, prof.access_pin_hash):
            auth_login(request, user)
            next_url = request.session.pop("sauron_pending_next", "/") or "/"
            request.session.pop(PENDING_KEY, None)
            return redirect(next_url)
        error = "Invalid PIN"
    return render(request, "registration/login_pin.html",
                  {"error": error, "username": user.username})
