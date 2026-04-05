"""Newsletter generation and distribution service."""
import os
import logging
from django.utils import timezone
from django.core.mail import send_mass_mail
from django.contrib.auth.models import User

logger = logging.getLogger(__name__)


def generate_newsletter_with_ai(newsletter, context_type="weekly"):
    """Use Claude to generate newsletter content."""
    from ai_agents.base_agent import BaseAgent

    # Gather context
    from signals.models import Signal
    from strategies.models import Strategy
    from scraping.models import NewsArticle
    from portfolio.services import get_or_create_default_portfolio
    from django.db.models import Avg

    now = timezone.now()
    if context_type == "weekly":
        from datetime import timedelta
        period = now - timedelta(days=7)
        period_label = "this week"
    else:
        period = now.replace(day=1, hour=0, minute=0, second=0)
        period_label = "this month"

    signals = Signal.objects.filter(created_at__gte=period)
    strategies = Strategy.objects.filter(created_at__gte=period)
    news = NewsArticle.objects.filter(published_at__gte=period).order_by("-published_at")[:20]

    prompt = f"""Generate a {context_type} trading newsletter for Sauron Vision platform.

Period: {period_label}
Active signals: {signals.filter(is_active=True).count()}
New signals generated: {signals.count()}
Bullish: {signals.filter(direction='bullish').count()}, Bearish: {signals.filter(direction='bearish').count()}
Avg signal score: {signals.aggregate(avg=Avg('score'))['avg'] or 0:.2f}
New strategies proposed: {strategies.filter(status='proposed').count()}
Active strategies: {strategies.filter(status__in=['active','approved']).count()}

Top news headlines:
{chr(10).join(f'- {n.title} ({n.source})' for n in news[:10])}

Target markets: {', '.join(newsletter.target_markets) if newsletter.target_markets else 'all'}

Write a professional, concise newsletter in markdown format with sections:
1. Market Overview (2-3 sentences)
2. Key Signals This Period
3. Strategy Performance
4. News Highlights
5. Outlook for Next Period
6. Risk Warnings

Keep it under 500 words. Professional tone, data-driven."""

    try:
        agent = BaseAgent(agent_name="newsletter_writer", model="claude-haiku-4-5-20251001")
        result = agent.call_api(prompt)
        newsletter.content_markdown = result
        newsletter.ai_prompt = prompt
        newsletter.status = "ai_generated"
        newsletter.save()
        return True
    except Exception as e:
        logger.error(f"Newsletter AI generation failed: {e}")
        newsletter.status = "failed"
        newsletter.content_markdown = f"AI generation failed: {e}"
        newsletter.save()
        return False


def send_newsletter(newsletter):
    """Distribute newsletter via selected channels."""
    from alerts.channels.telegram_alert import send_telegram

    if newsletter.status != "approved":
        return {"error": "Newsletter must be approved before sending"}

    recipients = User.objects.filter(is_active=True)
    sent_count = 0

    # Telegram
    if newsletter.send_telegram:
        try:
            send_telegram(f"SAURON VISION {newsletter.get_frequency_display()} Report",
                         newsletter.content_markdown[:4000])
            sent_count += 1
        except Exception as e:
            logger.error(f"Telegram newsletter send failed: {e}")

    # Email
    if newsletter.send_email:
        try:
            from django.core.mail import send_mail
            email_users = recipients.exclude(email="").values_list("email", flat=True)
            for email in email_users:
                try:
                    send_mail(
                        subject=f"Sauron Vision — {newsletter.title}",
                        message=newsletter.content_markdown,
                        from_email=os.getenv("DEFAULT_FROM_EMAIL", "noreply@sauronvision.com"),
                        recipient_list=[email],
                        fail_silently=True,
                    )
                    sent_count += 1
                except Exception:
                    pass
        except Exception as e:
            logger.error(f"Email newsletter send failed: {e}")

    # WhatsApp (via Twilio or similar — stub)
    if newsletter.send_whatsapp:
        logger.info("WhatsApp newsletter — requires Twilio integration")

    newsletter.status = "sent"
    newsletter.sent_at = timezone.now()
    newsletter.recipients_count = sent_count
    newsletter.save()

    return {"status": "sent", "recipients": sent_count}
