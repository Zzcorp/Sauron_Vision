"""Market data API views."""
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
    queryset = LiveQuote.objects.select_related("instrument").all()
    serializer_class = LiveQuoteSerializer


class EconomicCalendarView(generics.ListAPIView):
    queryset = EconomicEvent.objects.all()[:50]
    serializer_class = EconomicEventSerializer
