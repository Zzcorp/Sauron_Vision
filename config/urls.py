"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.shortcuts import render, redirect
from dashboard.auth_views import SauronLoginView, login_pin, login_pin_forgot
from core.health import health_check


def the_wall(request):
    """Public landing page — redirects authenticated users to dashboard."""
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "landing/the_wall.html")


urlpatterns = [
    path("healthz/", health_check, name="healthz"),
    path("admin/", admin.site.urls),
    path("wall/", the_wall, name="the_wall"),
    path("login/", SauronLoginView.as_view(), name="login"),
    path("login/pin/", login_pin, name="login_pin"),
    path("login/pin/forgot/", login_pin_forgot, name="login_pin_forgot"),
    path("logout/", auth_views.LogoutView.as_view(next_page="the_wall"), name="logout"),
    path("", include("bot_program.urls")),
    path("", include("dashboard.urls")),
]
