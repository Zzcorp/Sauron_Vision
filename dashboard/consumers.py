"""WebSocket consumers for real-time dashboard updates."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async


class DashboardConsumer(AsyncWebsocketConsumer):
    """Push live updates to dashboard clients."""

    async def connect(self):
        # Reject anonymous sockets — only authenticated sessions get the live
        # feed (the ASGI app wraps this router in AuthMiddlewareStack, so
        # scope["user"] is populated). Mirrors EyeConsumer.
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close()
            return
        self.group_name = "dashboard_live"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        # Send initial status
        await self.send(text_data=json.dumps({"type": "connected", "message": "Sauron Vision live feed active"}))

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data):
        """Handle incoming messages (subscribe to instruments)."""
        try:
            data = json.loads(text_data)
            msg_type = data.get("type", "")
            if msg_type == "subscribe":
                symbols = data.get("symbols", [])
                for symbol in symbols:
                    await self.channel_layer.group_add(f"instrument_{symbol}", self.channel_name)
        except json.JSONDecodeError:
            pass

    async def quote_update(self, event):
        """Push price quote update."""
        await self.send(text_data=json.dumps({
            "type": "quote",
            "data": event["data"],
        }))

    async def signal_fired(self, event):
        """Push new signal notification."""
        await self.send(text_data=json.dumps({
            "type": "signal",
            "data": event["data"],
        }))

    async def news_update(self, event):
        """Push news article."""
        await self.send(text_data=json.dumps({
            "type": "news",
            "data": event["data"],
        }))

    async def liquidation(self, event):
        """Push liquidation event to browsers."""
        await self.send(text_data=json.dumps({"type":"liquidation","data":event["data"]}))

    async def funding(self, event):
        """Push funding/mark-price tick."""
        await self.send(text_data=json.dumps({"type":"funding","data":event["data"]}))

    async def quote_stream(self, event):
        """Push real-time quote tick from Binance streamer."""
        await self.send(text_data=json.dumps({
            "type": "quote_stream",
            "data": event["data"],
        }))

    async def strategy_update(self, event):
        """Push strategy change."""
        await self.send(text_data=json.dumps({
            "type": "strategy",
            "data": event["data"],
        }))


def push_quote_update(symbol, price, change_pct):
    """Utility to push a quote update from any Celery task."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            "dashboard_live",
            {
                "type": "quote_update",
                "data": {"symbol": symbol, "price": str(price), "change_pct": str(change_pct)},
            }
        )


def push_signal_notification(signal_data):
    """Push a new signal to all connected clients."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            "dashboard_live",
            {"type": "signal_fired", "data": signal_data}
        )


def push_stream_update(symbol, last, change_pct, bid=0, ask=0, volume=0):
    """Broadcast a single live tick to all connected browsers."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync
    layer = get_channel_layer()
    if not layer:
        return
    async_to_sync(layer.group_send)(
        "dashboard_live",
        {"type": "quote_stream",
         "data": {"symbol": symbol, "last": last, "change_pct": change_pct,
                  "bid": bid, "ask": ask, "volume": volume}},
    )


def push_news_notification(article_data):
    """Push a news article to all connected clients."""
    from channels.layers import get_channel_layer
    from asgiref.sync import async_to_sync

    channel_layer = get_channel_layer()
    if channel_layer:
        async_to_sync(channel_layer.group_send)(
            "dashboard_live",
            {"type": "news_update", "data": article_data}
        )


# ── Phase 23 — per-user Eye WebSocket ─────────────────────────────────────

class EyeConsumer(AsyncWebsocketConsumer):
    """Per-user Eye dashboard push.

    Each user is in their own group `eye_user_<id>`; only their own
    orchestrator/trade events arrive. Unauthenticated connections are
    closed immediately so we never broadcast to anonymous sessions.
    """

    async def connect(self):
        user = self.scope.get("user")
        if user is None or not getattr(user, "is_authenticated", False):
            await self.close()
            return
        self.group_name = f"eye_user_{user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send(text_data=json.dumps({"type": "eye_connected"}))

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def eye_event(self, event):
        """Group handler — called by `push_eye_event`."""
        await self.send(text_data=json.dumps({
            "type": "eye_event",
            "kind": event.get("kind", ""),
            "data": event.get("data", {}),
        }))


def push_eye_event(user, kind: str, data: dict = None) -> bool:
    """Push a per-user Eye event from any sync caller (orchestrator, AssetBot).

    Returns True if a channel-layer dispatch happened. Safely returns False on:
      - missing/anonymous user
      - no channel_layer configured (dev environments without Redis)
      - any dispatch error (logged, never raises)
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    if not getattr(user, "id", None):
        return False
    try:
        from channels.layers import get_channel_layer
        from asgiref.sync import async_to_sync
        layer = get_channel_layer()
        if layer is None:
            return False
        async_to_sync(layer.group_send)(
            f"eye_user_{user.id}",
            {"type": "eye_event", "kind": kind, "data": data or {}},
        )
        return True
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("push_eye_event failed: %s", e)
        return False
