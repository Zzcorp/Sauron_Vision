"""Investor access — a read-only window onto a funded account.

Some accounts are funded on the broker and traded by the platform, and
the person whose money that is deserves to SEE it — value, curve, what
is deployed — without ever holding the levers. An investor is therefore
a real login with the narrowest citizenship this platform has: the gate
middleware (core/investor_gate.py) allows an investor session exactly
two destinations — their panel and the way out — and DENIES BY DEFAULT,
so every route the platform grows next year is investor-proof the day it
ships.

The link is one row: which investor sees which owner's book, under which
label, showing how much. Visibility is subtractive flags, not additive
grants — the panel starts at "value and curve" and the owner chooses
whether positions, history or dollar figures join it. `percents_only`
exists because an LP relationship often discloses performance, not size.

Revocation is one boolean. An inactive row logs the investor straight
back out at the gate — there is no half-revoked state.
"""
from django.conf import settings
from django.db import models


class InvestorAccess(models.Model):
    # The investor's own login. OneToOne: one investor account is one
    # window onto one book — a person invited to two funds gets two
    # logins, which keeps the gate's question ("where may THIS session
    # go?") one row wide.
    investor = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="investor_access")
    # The funded account whose book the panel renders.
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="investor_grants")

    label = models.CharField(
        max_length=120, blank=True,
        help_text="What the panel calls this book — 'Fund A', a mandate "
                  "name — instead of the internal username.")

    # Visibility flags — the panel's floor is value + equity curve.
    show_positions = models.BooleanField(
        default=False, help_text="Open positions, symbol by symbol.")
    show_history = models.BooleanField(
        default=False, help_text="Closed trades and realized outcomes.")
    percents_only = models.BooleanField(
        default=True,
        help_text="Performance without size: percentages and the curve's "
                  "shape, never dollar amounts.")

    is_active = models.BooleanField(default=True)
    created_by = models.CharField(max_length=80, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        state = "active" if self.is_active else "REVOKED"
        return (f"{self.investor.username} → {self.owner.username} "
                f"({self.label or 'unlabelled'}, {state})")
