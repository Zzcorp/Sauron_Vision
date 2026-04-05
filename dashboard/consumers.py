"""WebSocket consumers for real-time dashboard updates."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async


class DashboardConsumer(AsyncWebsocketConsumer):
    """Push live updates to dashboard clients."""

    async def connect(self):
        self.group_name = "dashboard_live"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        # Send initial status
        await self.send(text_data=json.dumps({"type": "connected", "message": "Sauron Vision live feed active"}))

    async def disconnect(self, close_code):
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
