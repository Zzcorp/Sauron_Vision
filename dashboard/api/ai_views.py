"""AI agent API views.

STAFF ONLY (2026-10-24). Both served every login: /api/ai/tasks/ the AI
ledger whole (every field of the newest 100 rows: the first 500 characters
of each prompt and answer and the structured output, of every agent, the
staff-only ones too: the position review, the council, the trade debate,
the strategist, the research desk), and /api/ai/briefing/ the strategy
advisor's whole answer, written from the book's value, cash and positions.
No page or script of the platform calls either; the operator's pages read
the ledger through their own views. Staff only, rather than a list of safe
agents: the ledger takes a row from every caller of the provider, and a
list would be wrong the day a new agent wrote one.
"""
from rest_framework import generics
from rest_framework.permissions import BasePermission
from rest_framework.views import APIView
from rest_framework.response import Response
from ai_agents.models import AgentTask
from dashboard.serializers import AgentTaskSerializer


class IsStaff(BasePermission):
    """A staff or superuser login (core.views_book.is_staff's rule)."""

    def has_permission(self, request, view):
        from core.views_book import is_staff
        return is_staff(request.user)


class AgentTaskListView(generics.ListAPIView):
    permission_classes = [IsStaff]
    queryset = AgentTask.objects.all()[:100]
    serializer_class = AgentTaskSerializer


class DailyBriefingView(APIView):
    permission_classes = [IsStaff]

    def get(self, request):
        latest = AgentTask.objects.filter(
            agent="strategy_advisor",
            success=True,
        ).first()

        if latest:
            return Response(latest.structured_output)
        return Response({"message": "No briefing available yet"})
