"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import render, redirect
from django.views.generic import RedirectView
from dashboard.auth_views import SauronLoginView, login_pin, login_pin_forgot
from core.health import health_check
from core.wall_facts import market_sessions, wall_facts


def the_wall(request):
    """Public landing page — redirects authenticated users to dashboard.

    `wall` carries the real platform counts (see core.wall_facts): the page
    used to hardcode them, so it kept claiming 667 green tests roughly 1,250
    tests later. wall_facts() is cached and cannot raise — this is the login
    gateway, and no counter is worth a 500 on the front door.
    """
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "landing/the_wall.html", {
        # Not cached with the facts: session state is clock arithmetic, and a
        # five-minute-stale "OPEN" is the kind of small lie this page forbids.
        "wall": wall_facts(),
        "sessions": market_sessions(),
    })


urlpatterns = [
    path("healthz/", health_check, name="healthz"),
    # Links that shipped inside notifications — and therefore inside
    # Telegram messages, emails and browser histories we cannot edit.
    # Repairing the stored rows fixes the inbox; these keep every copy
    # already out in the world from landing on a 404.
    path("market-data/", RedirectView.as_view(url="/quotes/", permanent=True)),
    path("dashboard/", RedirectView.as_view(url="/", permanent=True)),
    path("admin/", admin.site.urls),
    path("wall/", the_wall, name="the_wall"),
    path("login/", SauronLoginView.as_view(), name="login"),
    path("login/pin/", login_pin, name="login_pin"),
    path("login/pin/forgot/", login_pin_forgot, name="login_pin_forgot"),
    path("logout/", auth_views.LogoutView.as_view(next_page="the_wall"), name="logout"),
    path("", include("bot_program.urls")),
    path("", include("dashboard.urls")),
]
