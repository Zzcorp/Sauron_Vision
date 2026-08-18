"""Market data API views."""
from django.utils import timezone
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView
from instruments.models import Instrument
from market_data.models import LiveQuote, EconomicEvent
from dashboard.serializers import InstrumentSerializer, LiveQuoteSerializer, EconomicEventSerializer


class InstrumentListView(generics.ListAPIView):
    queryset = Instrument.objects.filter(is_active=True)
    serializer_class = InstrumentSerializer


class LiveQuoteListView(generics.ListAPIView):
    # LiveQuote has no usable Meta ordering here — pin to symbol so the ticker
    # list doesn't reshuffle between requests.
    queryset = LiveQuote.objects.select_related("instrument").order_by("instrument__symbol")
    serializer_class = LiveQuoteSerializer


class EconomicCalendarView(generics.ListAPIView):
    serializer_class = EconomicEventSerializer

    def get_queryset(self):
        # EconomicEvent's Meta orders by ascending datetime, so .all()[:50] served
        # the 50 OLDEST rows ever stored. The calendar wants upcoming events — and
        # timezone.now() must resolve per request (a class-level queryset would
        # freeze it at import time), hence the get_queryset override. No slice:
        # pagination caps the page at PAGE_SIZE, and the global OrderingFilter
        # 500s on ?ordering= against a sliced queryset.
        return (
            EconomicEvent.objects
            .filter(datetime__gte=timezone.now())
            .order_by("datetime")
        )
