"""Alert and newsletter models."""
from django.db import models
from django.contrib.auth.models import User


class AlertRule(models.Model):
    """User's personal signal alert rules."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="alert_rules")
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)

    # Trigger conditions
    instrument_symbol = models.CharField(max_length=20, blank=True)  # empty = all instruments
    asset_class = models.CharField(max_length=20, blank=True)  # empty = all classes
    min_score = models.FloatField(default=0.5)
    direction = models.CharField(max_length=10, blank=True)  # bullish, bearish, or empty=both
    urgency = models.CharField(max_length=10, blank=True)  # critical, high, medium, low

    # Channels
    notify_telegram = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    notify_whatsapp = models.BooleanField(default=False)
    notify_sms = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username}: {self.name}"


class Newsletter(models.Model):
    """Admin-created newsletter for distribution."""
    FREQ_CHOICES = [
        ("weekly", "Weekly"),
        ("monthly", "Monthly"),
        ("adhoc", "Ad-hoc"),
    ]
    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("ai_generated", "AI Generated — Pending Review"),
        ("approved", "Approved"),
        ("sent", "Sent"),
        ("failed", "Failed"),
    ]

    title = models.CharField(max_length=200)
    frequency = models.CharField(max_length=10, choices=FREQ_CHOICES, default="weekly")
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default="draft")

    # Content
    content_markdown = models.TextField(blank=True)
    content_html = models.TextField(blank=True)
    ai_prompt = models.TextField(blank=True, help_text="Prompt used to generate content")

    # Distribution
    send_telegram = models.BooleanField(default=True)
    send_email = models.BooleanField(default=True)
    send_whatsapp = models.BooleanField(default=False)

    # Targeting
    target_all_users = models.BooleanField(default=True)
    target_markets = models.JSONField(default=list, blank=True)  # ["stock", "forex", "crypto"]

    # Meta
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    recipients_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"[{self.status}] {self.title}"


class UserNotificationPrefs(models.Model):
    """User notification channel preferences."""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="notification_prefs")

    # Channels
    telegram_chat_id = models.CharField(max_length=50, blank=True)
    whatsapp_number = models.CharField(max_length=20, blank=True)
    email_notifications = models.BooleanField(default=True)
    sms_number = models.CharField(max_length=20, blank=True)

    # What to receive
    receive_signals = models.BooleanField(default=True)
    receive_strategies = models.BooleanField(default=True)
    receive_news_alerts = models.BooleanField(default=True)
    receive_portfolio_alerts = models.BooleanField(default=True)
    receive_weekly_newsletter = models.BooleanField(default=True)
    receive_monthly_newsletter = models.BooleanField(default=True)
    # Phase-20 bot/orchestrator events: fills, gate rejections, drawdown alerts.
    receive_bot_alerts = models.BooleanField(default=True,
        help_text="Bot fills, orchestrator gate rejections, drawdown limit warnings.")
    # Phase-43 daily strategist briefing push (06:00 UTC).
    receive_strategist_briefing = models.BooleanField(default=False,
        help_text="Daily Sauron's Mind strategist briefing — outlook + posture + ideas.")

    # Quiet hours (UTC)
    quiet_start = models.TimeField(null=True, blank=True)
    quiet_end = models.TimeField(null=True, blank=True)

    class Meta:
        verbose_name_plural = "User notification preferences"

    def __str__(self):
        return f"{self.user.username} notification prefs"


class Notification(models.Model):
    """In-app notification for the bell dropdown."""
    TYPES = [
        ("signal", "New Signal"),
        ("strategy", "Strategy Update"),
        ("news", "Breaking News"),
        ("portfolio", "Portfolio Alert"),
        ("system", "System Message"),
        ("newsletter", "Newsletter"),
        ("bot", "Bot Event"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=TYPES)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=200, blank=True)  # Link to the relevant page
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # unread_count runs on EVERY page render (bell badge).
            models.Index(fields=["user", "read"]),
        ]

    def __str__(self):
        return f"[{'READ' if self.read else 'NEW'}] {self.title}"

    @staticmethod
    def safe_url(url: str) -> str:
        """The url a notification stores, but only if it resolves.

        `url` is free text and producers have shipped literal 404s
        ("/market-data/" lived for months). An unresolvable path is stored
        as "" — the bell then opens the detail popup instead of a dead
        page. External http(s) links pass through untouched.
        """
        u = (url or "").strip()
        if not u:
            return ""
        if u.startswith(("http://", "https://")):
            return u
        from django.urls import Resolver404, resolve
        try:
            resolve(u.split("?")[0].split("#")[0])
            return u
        except (Resolver404, ValueError):
            import logging
            logging.getLogger(__name__).warning(
                "[alerts] notification url %r does not resolve — storing "
                "empty so the click opens the detail popup instead of a "
                "404", u)
            return ""

    @classmethod
    def create_for_all(cls, notification_type, title, body="", url=""):
        """Create a notification for all active users."""
        from django.contrib.auth.models import User as U
        url = cls.safe_url(url)
        notifs = []
        for user in U.objects.filter(is_active=True):
            notifs.append(cls(
                user=user, notification_type=notification_type,
                title=title, body=body, url=url,
            ))
        cls.objects.bulk_create(notifs)
        # bulk_create fires no post_save — this loop is the explicit
        # complement to the receiver below. Each push lands only on ITS
        # user's per-user socket group, so there is no fan-out flood.
        for n in notifs:
            _push_live(n)
        return len(notifs)

    @classmethod
    def create_for_user(cls, user, notification_type, title, body="", url=""):
        """Create a notification for a specific user."""
        return cls.objects.create(
            user=user, notification_type=notification_type,
            title=title, body=body, url=cls.safe_url(url),
        )

    @classmethod
    def unread_count(cls, user):
        return cls.objects.filter(user=user, read=False).count()

    @classmethod
    def recent(cls, user, limit=15):
        return cls.objects.filter(user=user).order_by("-created_at")[:limit]


def _push_live(notification):
    """Announce a freshly created notification on its user's live socket.

    The browser turns it into a 4s hover-pausing banner and a bell-badge
    refresh. Best-effort by construction: a broken channel layer must
    never break notification creation, and quiet hours are respected only
    for EXTERNAL channels — the in-app row (and therefore this banner)
    always exists, matching the settings page's own promise.

    Producers that already raise a richer banner for the same event (bot
    fills) set `_banner_silent` on the instance before save: the push
    still goes out so the badge moves, but the client draws no card.
    """
    try:
        from dashboard.consumers import push_eye_event
        push_eye_event(notification.user, "notification", {
            "id": notification.pk,
            "type": notification.notification_type,
            "title": notification.title,
            "body": (notification.body or "")[:140],
            "url": notification.url or "/notifications/",
            "silent": bool(getattr(notification, "_banner_silent", False)),
        })
    except Exception:  # noqa: BLE001 — the row matters, the push is gravy
        import logging
        logging.getLogger(__name__).debug(
            "live notification push failed", exc_info=True)


from django.db.models.signals import post_save  # noqa: E402
from django.dispatch import receiver  # noqa: E402


@receiver(post_save, sender=Notification)
def _notification_created(sender, instance, created, **kwargs):
    """Every save-path creation pushes live — .objects.create,
    create_for_user, and the five direct-create producer sites alike.
    bulk_create (create_for_all) is complemented explicitly above."""
    if created:
        _push_live(instance)


class PriceAlert(models.Model):
    """User-defined price alert."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='price_alerts')
    instrument = models.ForeignKey('instruments.Instrument', on_delete=models.CASCADE)
    condition = models.CharField(max_length=10, choices=[
        ('above', 'Price Above'),
        ('below', 'Price Below'),
        ('cross', 'Price Crosses'),
    ])
    target_price = models.DecimalField(max_digits=20, decimal_places=8)
    triggered = models.BooleanField(default=False)
    triggered_at = models.DateTimeField(null=True, blank=True)
    notify_telegram = models.BooleanField(default=True)
    notify_email = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.instrument.symbol} {self.condition} {self.target_price}"


def check_price_alerts():
    """Check all active price alerts against current prices."""
    import logging
    from market_data.models import LiveQuote
    from django.utils import timezone

    logger = logging.getLogger(__name__)
    alerts = PriceAlert.objects.filter(triggered=False).select_related('instrument', 'user')
    triggered_count = 0

    for alert in alerts:
        try:
            quote = LiveQuote.objects.get(instrument=alert.instrument)
            current_price = quote.last

            should_trigger = False
            if alert.condition == 'above' and current_price >= alert.target_price:
                should_trigger = True
            elif alert.condition == 'below' and current_price <= alert.target_price:
                should_trigger = True
            elif alert.condition == 'cross':
                should_trigger = current_price >= alert.target_price or current_price <= alert.target_price

            if should_trigger:
                alert.triggered = True
                alert.triggered_at = timezone.now()
                alert.save()

                title = f"Price Alert: {alert.instrument.symbol} {alert.condition} {alert.target_price}"
                body = f"Current price: {current_price}. {alert.note}" if alert.note else f"Current price: {current_price}"
                Notification.create_for_user(alert.user, 'portfolio', title, body)

                if alert.notify_telegram:
                    try:
                        from alerts.channels.telegram_alert import send_telegram
                        prefs = alert.user.notification_prefs
                        if prefs.telegram_chat_id:
                            send_telegram(prefs.telegram_chat_id, f"🔔 {title}\n{body}")
                    except Exception:
                        pass

                if alert.notify_email:
                    try:
                        from alerts.channels.email_alert import send_email_to_user
                        send_email_to_user(alert.user, title, body)
                    except Exception:
                        pass

                triggered_count += 1
        except Exception as e:
            logger.error(f"Price alert check failed for {alert.id}: {e}")

    return triggered_count


class WebhookEndpoint(models.Model):
    """User-configured webhook for receiving alerts (Zapier/IFTTT compatible)."""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='webhooks')
    name = models.CharField(max_length=100)
    url = models.URLField()
    secret = models.CharField(max_length=100, blank=True, help_text="Shared secret for HMAC signing")
    is_active = models.BooleanField(default=True)

    # What events to send
    on_signal = models.BooleanField(default=True)
    on_trade = models.BooleanField(default=True)
    on_alert = models.BooleanField(default=True)
    on_portfolio = models.BooleanField(default=False)
    on_news = models.BooleanField(default=False)

    # Stats
    total_sent = models.IntegerField(default=0)
    last_sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    consecutive_failures = models.IntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.username}: {self.name} ({'active' if self.is_active else 'disabled'})"
