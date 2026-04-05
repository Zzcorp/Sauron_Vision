"""Scraped data models — news, sentiment, institutional filings."""
from django.db import models
from instruments.models import Instrument


class NewsArticle(models.Model):
    """News articles from scraped sources and APIs."""
    title = models.CharField(max_length=500)
    source = models.CharField(max_length=100)
    url = models.URLField(unique=True)
    published_at = models.DateTimeField()
    content_summary = models.TextField(blank=True)
    raw_content = models.TextField(blank=True)

    # AI-generated fields (filled by news_analyst agent)
    ai_sentiment_score = models.FloatField(null=True, blank=True)
    ai_urgency = models.CharField(max_length=20, blank=True)
    ai_summary = models.TextField(blank=True)
    ai_affected_instruments = models.ManyToManyField(Instrument, blank=True, related_name="news_articles")
    ai_processed_at = models.DateTimeField(null=True, blank=True)

    scraped_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-published_at"]

    def __str__(self):
        return f"[{self.source}] {self.title[:80]}"


class SentimentSnapshot(models.Model):
    """Aggregated sentiment per instrument from social sources."""
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="sentiment_snapshots")
    source = models.CharField(max_length=50)
    timestamp = models.DateTimeField()
    bullish_count = models.IntegerField(default=0)
    bearish_count = models.IntegerField(default=0)
    neutral_count = models.IntegerField(default=0)
    composite_score = models.FloatField()
    volume = models.IntegerField(default=0)
    trending = models.BooleanField(default=False)

    class Meta:
        indexes = [
            models.Index(fields=["instrument", "source", "-timestamp"]),
        ]
        ordering = ["-timestamp"]


class COTReport(models.Model):
    """CFTC Commitments of Traders data."""
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="cot_reports")
    report_date = models.DateField()
    commercial_long = models.BigIntegerField()
    commercial_short = models.BigIntegerField()
    non_commercial_long = models.BigIntegerField()
    non_commercial_short = models.BigIntegerField()
    open_interest = models.BigIntegerField()
    net_speculative = models.BigIntegerField()

    class Meta:
        unique_together = ["instrument", "report_date"]
        ordering = ["-report_date"]


class InstitutionalFiling(models.Model):
    """SEC 13F and Form 4 data."""
    filing_type = models.CharField(max_length=10)
    filer_name = models.CharField(max_length=300)
    instrument = models.ForeignKey(Instrument, on_delete=models.CASCADE, related_name="institutional_filings")
    filing_date = models.DateField()
    shares = models.BigIntegerField(null=True)
    value = models.DecimalField(max_digits=20, decimal_places=2, null=True)
    change_type = models.CharField(max_length=20, blank=True)
    change_pct = models.FloatField(null=True)
    source_url = models.URLField(blank=True)

    class Meta:
        ordering = ["-filing_date"]


class OptionsFlow(models.Model):
    """Unusual options activity tracking."""
    instrument = models.ForeignKey("instruments.Instrument", on_delete=models.CASCADE, related_name="options_flow")
    timestamp = models.DateTimeField()
    contract_type = models.CharField(max_length=4)
    strike = models.DecimalField(max_digits=20, decimal_places=2)
    expiry = models.DateField()
    volume = models.IntegerField()
    open_interest = models.IntegerField(default=0)
    premium = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    sentiment = models.CharField(max_length=10)
    is_unusual = models.BooleanField(default=False)
    source = models.CharField(max_length=50)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.instrument.symbol} {self.contract_type.upper()} {self.strike}"
