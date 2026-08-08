"""WebSocket routing for live dashboard updates."""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r"ws/dashboard/$", consumers.DashboardConsumer.as_asgi()),
    # Phase 23 — per-user Eye real-time push.
    re_path(r"ws/eye/$", consumers.EyeConsumer.as_asgi()),
]
