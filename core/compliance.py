"""Regulatory compliance — trading restrictions, blackout periods, position limits."""
import logging
from django.db import models
from django.utils import timezone

logger = logging.getLogger(__name__)


class TradingRestriction(models.Model):
    """Trading restrictions and blackout periods."""
    RESTRICTION_TYPES = [
        ('blackout', 'Blackout Period'),
        ('position_limit', 'Position Limit'),
        ('instrument_ban', 'Instrument Ban'),
        ('daily_limit', 'Daily Trading Limit'),
    ]

    user = models.ForeignKey('auth.User', on_delete=models.CASCADE, related_name='trading_restrictions', null=True, blank=True)
    restriction_type = models.CharField(max_length=20, choices=RESTRICTION_TYPES)
    instrument_symbol = models.CharField(max_length=20, blank=True)  # empty = all
    description = models.TextField()

    # For blackout periods
    start_date = models.DateTimeField(null=True, blank=True)
    end_date = models.DateTimeField(null=True, blank=True)

    # For position limits
    max_quantity = models.DecimalField(max_digits=20, decimal_places=8, null=True, blank=True)
    max_value = models.DecimalField(max_digits=20, decimal_places=2, null=True, blank=True)

    # For daily limits
    max_trades_per_day = models.IntegerField(null=True, blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = 'core'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.restriction_type}] {self.description[:50]}"


class ComplianceChecker:
    """Check trades against compliance rules before execution."""

    def check_trade(self, user, symbol, action, quantity=None, value=None):
        """Check if a trade is allowed under current restrictions.

        Returns (is_allowed, reasons) tuple.
        """
        now = timezone.now()
        violations = []

        restrictions = TradingRestriction.objects.filter(
            is_active=True,
        ).filter(
            models.Q(user=user) | models.Q(user__isnull=True)
        )

        for r in restrictions:
            if r.instrument_symbol and r.instrument_symbol != symbol:
                continue

            if r.restriction_type == 'blackout':
                if r.start_date and r.end_date:
                    if r.start_date <= now <= r.end_date:
                        violations.append(f"Blackout period active: {r.description}")

            elif r.restriction_type == 'instrument_ban':
                violations.append(f"Instrument banned: {r.description}")

            elif r.restriction_type == 'position_limit':
                if quantity and r.max_quantity and quantity > r.max_quantity:
                    violations.append(f"Exceeds position limit of {r.max_quantity}")
                if value and r.max_value and value > r.max_value:
                    violations.append(f"Exceeds value limit of {r.max_value}")

            elif r.restriction_type == 'daily_limit':
                if r.max_trades_per_day:
                    from portfolio.models import Position
                    from portfolio.services import get_or_create_default_portfolio
                    portfolio = get_or_create_default_portfolio(user=user)
                    today_start = now.replace(hour=0, minute=0, second=0)
                    today_trades = Position.objects.filter(
                        portfolio=portfolio, opened_at__gte=today_start
                    ).count()
                    if today_trades >= r.max_trades_per_day:
                        violations.append(f"Daily trade limit reached ({r.max_trades_per_day})")

        return (len(violations) == 0, violations)

    def get_active_restrictions(self, user=None):
        """Get all active restrictions for a user."""
        now = timezone.now()
        qs = TradingRestriction.objects.filter(is_active=True)

        if user:
            qs = qs.filter(models.Q(user=user) | models.Q(user__isnull=True))

        restrictions = []
        for r in qs:
            entry = {
                'id': r.id,
                'type': r.restriction_type,
                'description': r.description,
                'symbol': r.instrument_symbol or 'all',
                'is_active_now': True,
            }

            if r.restriction_type == 'blackout' and r.start_date and r.end_date:
                entry['start'] = r.start_date.isoformat()
                entry['end'] = r.end_date.isoformat()
                entry['is_active_now'] = r.start_date <= now <= r.end_date

            restrictions.append(entry)

        return restrictions
