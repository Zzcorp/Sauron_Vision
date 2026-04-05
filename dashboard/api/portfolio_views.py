"""Portfolio API views."""
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from portfolio.models import Portfolio, Position, PortfolioSnapshot
from dashboard.serializers import PortfolioSerializer, PositionSerializer, SnapshotSerializer


class PortfolioView(APIView):
    def get(self, request):
        from portfolio.services import get_or_create_default_portfolio
        portfolio = get_or_create_default_portfolio()
        serializer = PortfolioSerializer(portfolio)
        return Response(serializer.data)


class PositionListView(generics.ListAPIView):
    serializer_class = PositionSerializer

    def get_queryset(self):
        return Position.objects.filter(closed_at__isnull=True).select_related("instrument", "strategy")


class SnapshotListView(generics.ListAPIView):
    queryset = PortfolioSnapshot.objects.all()[:90]
    serializer_class = SnapshotSerializer
