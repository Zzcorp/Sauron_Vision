"""Options flow tracking model."""
from django.db import models
from instruments.models import Instrument


class OptionsFlow(models.Model):
    """Unusual options activity."""
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="options_flow")
    timestamp = models.DateTimeField()
    contract_type = models.CharField(max_length=4)  # "call" or "put"
    strike = models.DecimalField(max_digits=20, decimal_places=2)
    expiry = models.DateField()
    volume = models.IntegerField()
    open_interest = models.IntegerField(default=0)
    premium = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sentiment = models.CharField(max_length=10)  # "bullish", "bearish", "neutral"
    is_unusual = models.BooleanField(default=False)
    source = models.CharField(max_length=50)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.contract_type.upper()} {self.strike} exp {self.expiry}"
