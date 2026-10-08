"""Sauron Vision — Root URL Configuration."""
from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.views.generic import RedirectView
from dashboard.auth_views import SauronLoginView, login_pin, login_pin_forgot
from core.health import health_check
from core.views_book import the_book
from core.views_wall import the_wall


urlpatterns = [
    path("healthz/", health_check, name="healthz"),
    # Links that shipped inside notifications — and therefore inside
    # Telegram messages, emails and browser histories we cannot edit.
    # Repairing the stored rows fixes the inbox; these keep every copy
    # already out in the world from landing on a 404.
    path("market-data/", RedirectView.as_view(url="/quotes/", permanent=True)),
    path("dashboard/", RedirectView.as_view(url="/", permanent=True)),
    path("admin/", admin.site.urls),
    # The Wall (core/views_wall.py since 2026-10-08): the public front door
    # and the login gateway, rendered without the context processors, every
    # reader fenced, counts out of core.wall_facts.
    path("wall/", the_wall, name="the_wall"),
    # The Book of Sauron (2026-09-27): the story, the machine and the road
    # so far. Public like the Wall; a signed-in staff user alone is sent
    # one more chapter (core/views_book.py).
    path("book/", the_book, name="the_book"),
    path("login/", SauronLoginView.as_view(), name="login"),
    path("login/pin/", login_pin, name="login_pin"),
    path("login/pin/forgot/", login_pin_forgot, name="login_pin_forgot"),
    path("logout/", auth_views.LogoutView.as_view(next_page="the_wall"), name="logout"),
    path("", include("bot_program.urls")),
    path("", include("dashboard.urls")),
]
