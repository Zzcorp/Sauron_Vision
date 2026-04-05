"""Strategy API views."""
from rest_framework import generics
from strategies.models import Strategy
from dashboard.serializers import StrategySerializer


class StrategyListView(generics.ListAPIView):
    queryset = Strategy.objects.all()
    serializer_class = StrategySerializer


class StrategyDetailView(generics.RetrieveAPIView):
    queryset = Strategy.objects.all()
    serializer_class = StrategySerializer
