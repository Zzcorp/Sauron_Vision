"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.http import JsonResponse
from dashboard.auth_views import SauronLoginView, login_pin


def healthz(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("healthz/", healthz, name="healthz"),
    path("admin/", admin.site.urls),
    path("login/", SauronLoginView.as_view(), name="login"),
    path("login/pin/", login_pin, name="login_pin"),
    path("logout/", auth_views.LogoutView.as_view(next_page="login"), name="logout"),
    path("", include("bot_program.urls")),
    path("", include("dashboard.urls")),
]
