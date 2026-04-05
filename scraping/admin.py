from django.contrib import admin
from .models import NewsArticle, SentimentSnapshot, COTReport, InstitutionalFiling


@admin.register(NewsArticle)
class NewsArticleAdmin(admin.ModelAdmin):
    list_display = ["title", "source", "published_at", "ai_sentiment_score", "ai_urgency"]
    list_filter = ["source", "ai_urgency"]
    search_fields = ["title"]


@admin.register(SentimentSnapshot)
class SentimentSnapshotAdmin(admin.ModelAdmin):
    list_display = ["instrument", "source", "timestamp", "composite_score", "volume", "trending"]
    list_filter = ["source", "trending"]


@admin.register(COTReport)
class COTReportAdmin(admin.ModelAdmin):
    list_display = ["instrument", "report_date", "net_speculative", "open_interest"]


@admin.register(InstitutionalFiling)
class InstitutionalFilingAdmin(admin.ModelAdmin):
    list_display = ["filer_name", "instrument", "filing_type", "filing_date", "change_type"]
    list_filter = ["filing_type", "change_type"]
