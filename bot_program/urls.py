from django.urls import path
from . import views

urlpatterns = [
    path("bot/",                   views.bot_home,         name="bot_home"),
    path("bot/link/",              views.link_binance,     name="bot_link"),
    path("bot/configure/",         views.configure_bot,    name="bot_configure"),
    path("bot/toggle/",            views.toggle_bot,       name="bot_toggle"),
    path("bot/tick/",              views.run_tick_now,     name="bot_tick"),
    path("bot/scenarios/",         views.scenarios_list,   name="scenarios_list"),
    path("bot/scenarios/new/",     views.scenario_new,     name="scenario_new"),
    path("bot/scenarios/<int:pk>/",views.scenario_detail,  name="scenario_detail"),
]
