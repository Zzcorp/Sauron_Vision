"""A WithdrawalRequest — money asked for IN ADVANCE, held back before it leaves.

The operator and Gandalf (his father, who signs in on the SAME account and
knows the trading PIN) asked for one thing, 2026-09-28: to be able to say
ahead of time "I will take X out of the real account", without the
platform selling anything to find it. So a request does not touch a
position, a share or a plan. It RESERVES an amount, and from that moment
the platform simply stops deploying it:

  * every pool that follows the account is sized from the reading LESS the
    reserve (tasks._follow_the_account), so all of them shrink by the same
    proportion and their shares of the account are unchanged;
  * the eToro cash gate (AssetBot._leverage_headroom) will not pledge the
    reserved cash to a new order;
  * nothing closes. The bots keep trading their plan, and cash builds up
    as positions close on their own.

When the money is actually sent at the broker, the request is marked PAID
with the amount and the moment — and from then on it is a cash FLOW, not
a loss: the drawdown governor and the shock detector compare readings
taken before it with readings taken after it on the same footing
(bot_program.withdrawals.flow_adjusted_value). Without that, the first
real withdrawal would read as a crash and de-risk the whole account.

The session cannot tell the two men apart — it is one login — so the
request says who asked (`requested_by`) and who closed it (`acted_by`)
in their own words, chosen on the form. Every state change takes the
trading PIN; the page is /withdrawals/.

`currency` is fixed at creation to the account reading's currency. "USD"
is written only when no reading has ever landed, and the page says so:
nothing here converts, and a reserve is subtracted from the reading as a
number, which is the conservative direction if the two ever differ. That
fallback is flagged (`currency_assumed`) and replaced by the reading's
real currency when the request is marked withdrawn; a request in a REAL
currency other than the reading's cannot be marked withdrawn at all
(bot_program.withdrawals.mark_paid says why, in plain words).
"""
from django.conf import settings
from django.db import models


class WithdrawalRequest(models.Model):
    WHO_OPERATOR = "operator"
    WHO_GANDALF = "gandalf"
    WHO_CHOICES = [
        (WHO_OPERATOR, "The operator"),
        (WHO_GANDALF, "Gandalf"),
    ]

    STATUS_RESERVED = "reserved"
    STATUS_PAID = "paid"
    STATUS_CANCELLED = "cancelled"
    STATUS_CHOICES = [
        # Active: held back from every new sizing until it is paid or
        # cancelled. The only state the reserve arithmetic reads.
        (STATUS_RESERVED, "Reserved"),
        # Withdrawn at the broker. A cash flow from here on — the equity
        # history is compared net of it, never read as a loss.
        (STATUS_PAID, "Withdrawn"),
        (STATUS_CANCELLED, "Cancelled"),
    ]

    # The BOOK owner — request.user. Both men act on this one account.
    user = models.ForeignKey(settings.AUTH_USER_MODEL,
                             on_delete=models.CASCADE,
                             related_name="withdrawal_requests")
    requested_by = models.CharField(max_length=16, choices=WHO_CHOICES)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    currency = models.CharField(max_length=8, default="USD")
    # True when `currency` is the stated fallback, written because no
    # reading (or a reading without a currency) had landed — a guess, not a
    # fact. Such a request is read as "the account's own currency" wherever
    # a currency is compared (the eToro cash gate, the flow accounting), and
    # marking it withdrawn stamps the reading's real currency on it. Without
    # this, a request filed before the first reading kept "USD" for ever,
    # and an account that then read in EUR never counted its withdrawal as
    # a flow: the history read it as a loss (review, 2026-09-28).
    currency_assumed = models.BooleanField(default=False)
    # The date the money is wanted by, when there is one. Informational:
    # the reserve starts the moment the request is filed, whatever it says.
    wanted_by = models.DateField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES,
                              default=STATUS_RESERVED, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # When the money left at the broker, and how much actually left — the
    # two numbers the flow accounting needs. Editable on the form, because
    # the moment that matters is the moment the BROKER's balance moved.
    paid_at = models.DateTimeField(null=True, blank=True)
    paid_amount = models.DecimalField(max_digits=14, decimal_places=2,
                                      null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    closing_note = models.TextField(blank=True, default="")
    # Who marked it withdrawn or cancelled — "" while it is still reserved.
    acted_by = models.CharField(max_length=16, choices=WHO_CHOICES,
                                blank=True, default="")

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
        ]
        constraints = [
            # A withdrawal of nothing, or of less than nothing, is not a
            # request: the form refuses it, and so does the table.
            models.CheckConstraint(condition=models.Q(amount__gt=0),
                                   name="withdrawal_amount_positive"),
        ]

    @property
    def is_active(self) -> bool:
        return self.status == self.STATUS_RESERVED

    @property
    def flow_amount(self):
        """What left the account: the amount actually paid, or the amount
        asked for when a paid row never recorded one."""
        return self.paid_amount if self.paid_amount is not None \
            else self.amount

    def __str__(self):
        return (f"<WithdrawalRequest #{self.pk} {self.amount} "
                f"{self.currency} {self.status}>")
