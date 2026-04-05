"""Signal API views."""
from rest_framework import generics
from signals.models import Signal
from dashboard.serializers import SignalSerializer


class SignalListView(generics.ListAPIView):
    queryset = Signal.objects.select_related("instrument").all()[:100]
    serializer_class = SignalSerializer


class ActiveSignalListView(generics.ListAPIView):
    queryset = Signal.objects.filter(is_active=True).select_related("instrument")
    serializer_class = SignalSerializer
