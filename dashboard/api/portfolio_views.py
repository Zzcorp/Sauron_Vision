"""Portfolio API views."""
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from portfolio.models import Portfolio, Position, PortfolioSnapshot
from dashboard.serializers import PortfolioSerializer, PositionSerializer, SnapshotSerializer


# Every view here is scoped to the CALLER'S OWN book.
#
# They were not. `PortfolioView` served the shared "Main" row, and the two
# list views were unscoped entirely — `Position.objects.filter(closed_at
# __isnull=True)` returns every portfolio's open positions and the snapshot
# queryset every portfolio's equity history. The permission class is
# IsAuthenticated, so on an install with more than one operator any logged-in
# user could read the others' positions, sizes and entry prices through the
# API while the pages they can actually see show only their own.


def _own_book(request):
    from portfolio.services import get_or_create_default_portfolio
    return get_or_create_default_portfolio(user=request.user)


class PortfolioView(APIView):
    def get(self, request):
        serializer = PortfolioSerializer(_own_book(request))
        return Response(serializer.data)


class PositionListView(generics.ListAPIView):
    serializer_class = PositionSerializer

    def get_queryset(self):
        return (Position.objects
                .filter(portfolio=_own_book(self.request), closed_at__isnull=True)
                .select_related("instrument", "strategy"))


class SnapshotListView(generics.ListAPIView):
    serializer_class = SnapshotSerializer

    def get_queryset(self):
        # A queryset evaluated at CLASS level is also a queryset built once
        # per process, so the slice was frozen at import time as well as
        # being unscoped.
        return PortfolioSnapshot.objects.filter(
            portfolio=_own_book(self.request)).order_by("-date")[:90]
