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
        ("briefing", "Sauron Briefing"),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    notification_type = models.CharField(max_length=20, choices=TYPES)
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    url = models.CharField(max_length=200, blank=True)  # Link to the relevant page
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    # Structured detail for the hover/click card: whatever the producer
    # knew and the one-line body had to flatten. The anomaly alert names
    # seven symbols in prose and can only link ONE page — here it carries
    # them as {"items": [{"label", "detail", "url"}, ...]} so the card can
    # offer each underlying asset as its own link.
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # unread_count runs on EVERY page render (bell badge).
            models.Index(fields=["user", "read"]),
        ]

    def __str__(self):
        return f"[{'READ' if self.read else 'NEW'}] {self.title}"

    # Paths producers have shipped that were never pages. They resolve now
    # (config/urls.py redirects them, for the copies already sitting in
    # Telegram messages and inboxes), so the resolve check below can no
    # longer catch them — a stored notification should carry the real
    # destination rather than lean on a compatibility shim.
    LEGACY_URL_REWRITES = {
        "/market-data/": "/quotes/",
        "/dashboard/": "/",
    }

    @staticmethod
    def safe_url(url: str) -> str:
        """The url a notification stores, but only if it goes somewhere.

        `url` is free text and producers have shipped literal 404s
        ("/market-data/" lived for months). Known-dead paths are rewritten
        to the page they meant; anything else that does not resolve is
        stored as "" — the bell then opens the detail popup instead of a
        dead page. External http(s) links pass through untouched.
        """
        u = (url or "").strip()
        if not u:
            return ""
        if u.startswith(("http://", "https://")):
            return u
        u = Notification.LEGACY_URL_REWRITES.get(u, u)
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
    def create_for_all(cls, notification_type, title, body="", url="",
                       data=None):
        """Create a notification for all active users.

        `data` lands on EVERY row, not just the first: the fan-out is one
        event seen by many people, and a card that offered the anomaly's
        seven symbols to whoever happened to be user #1 and a bare title
        to everyone else would be the same defect one layer down.
        """
        from django.contrib.auth.models import User as U
        url = cls.safe_url(url)
        data = data or {}
        notifs = []
        for user in U.objects.filter(is_active=True):
            notifs.append(cls(
                user=user, notification_type=notification_type,
                title=title, body=body, url=url, data=data,
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
    # Which side of the target the price was on when this alert was first
    # SEEN by the checker. A 'cross' has to be measured from somewhere: the
    # condition asks whether the price moved across the level, and with no
    # remembered side there is nothing to move across.
    baseline_price = models.DecimalField(max_digits=20, decimal_places=8,
                                         null=True, blank=True)
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


# A quote older than this is not a market price any more. An alert fired
# against a fossil says a level broke "now" when it broke, or did not break,
# at some unknown time before the feed stopped: the operator reads Friday's
# close on Sunday and opens a position into Monday's gap.
#
# An hour, not the 900s the trading paths use. Those read quotes for
# instruments a bot is actively working, which the streamers keep fresh; an
# ALERT can be set on anything in the catalogue, including instruments only
# the ten-minute yfinance sweep covers — and that sweep runs against
# hundreds of symbols, so an individual one can easily be twenty minutes
# stale while the platform is perfectly healthy. At 900s those alerts would
# never fire at all, silently, which is a worse failure than firing on a
# price a few minutes old.
QUOTE_MAX_AGE_SECONDS = 3600


def _cross_triggered(alert, price) -> bool:
    """Has the price moved to the OTHER side of the target since we started
    watching this alert?

    'cross' used to read `price >= target or price <= target`, which is true
    of every finite number: the alert fired on the first beat whatever the
    market was doing, sent its notification, and — being consumed — could
    never fire when the level was actually crossed.

    A crossing needs a side to cross FROM, so the first sighting arms the
    alert (records the side, fires nothing) and every later beat compares
    against it. That does mean an alert created on the wrong side of the
    target waits for the price to come back through the level, which is what
    'crosses' means; 'above' and 'below' are there for "is it past it".
    """
    from decimal import Decimal
    target = Decimal(str(alert.target_price))
    now_above = Decimal(str(price)) >= target
    baseline = alert.baseline_price
    if baseline is None:
        # Conditional so two workers arming the same alert in the same beat
        # record one baseline rather than the later one overwriting the
        # earlier — a rewritten baseline is a crossing erased.
        PriceAlert.objects.filter(pk=alert.pk, baseline_price__isnull=True
                                  ).update(baseline_price=price)
        alert.baseline_price = price
        return False
    return (Decimal(str(baseline)) >= target) != now_above


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
            quote = LiveQuote.objects.filter(instrument=alert.instrument).first()
            if quote is None:
                continue
            age = (timezone.now() - quote.updated_at).total_seconds()
            if age > QUOTE_MAX_AGE_SECONDS:
                logger.debug("price alert %s: %s quote is %.0fs old — not a "
                             "price to fire an alert on", alert.id,
                             alert.instrument.symbol, age)
                continue
            current_price = quote.last

            should_trigger = False
            if alert.condition == 'above' and current_price >= alert.target_price:
                should_trigger = True
            elif alert.condition == 'below' and current_price <= alert.target_price:
                should_trigger = True
            elif alert.condition == 'cross':
                should_trigger = _cross_triggered(alert, current_price)

            if should_trigger:
                # Claim the row instead of saving a snapshot loaded who knows
                # how many seconds ago. This beat runs every 60s on a queue
                # with two worker slots, and one pass sends a Telegram POST
                # and an SMTP mail per firing alert — so a busy open runs
                # long enough for the next copy to start on rows this one has
                # not reached. `save()` on the stale row also wrote back every
                # field, reverting a target_price the user edited meanwhile.
                # A conditional UPDATE makes the claim the same act as the
                # test: exactly one worker gets a 1 back. `target_price` is
                # in the condition too, so an edit that landed while this
                # pass was deciding cancels the decision it invalidated —
                # the next beat re-asks against the level the user now
                # wants, instead of firing on the one they just changed.
                claimed = PriceAlert.objects.filter(
                    pk=alert.pk, triggered=False,
                    target_price=alert.target_price).update(
                        triggered=True, triggered_at=timezone.now())
                if not claimed:
                    continue

                title = f"Price Alert: {alert.instrument.symbol} {alert.condition} {alert.target_price}"
                body = f"Current price: {current_price}. {alert.note}" if alert.note else f"Current price: {current_price}"
                from alerts.links import page_url
                # The user set this alert on one instrument and the row
                # carries it — shipping no url at all sent them back to the
                # inbox to look up the symbol the title had already named.
                Notification.create_for_user(
                    alert.user, 'portfolio', title, body,
                    url=page_url("instrument_detail", alert.instrument.symbol))

                if alert.notify_telegram:
                    try:
                        from alerts.channels.telegram_alert import send_telegram
                        prefs = alert.user.notification_prefs
                        if prefs.telegram_chat_id:
                            # No leading mark for Telegram — the title already
                            # opens with "Price Alert:", and a glyph here is
                            # at the mercy of the reader's client font.
                            send_telegram(prefs.telegram_chat_id, f"{title}\n{body}")
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
