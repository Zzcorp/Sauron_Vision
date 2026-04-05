"""AI agent API views."""
from rest_framework import generics
from rest_framework.views import APIView
from rest_framework.response import Response
from ai_agents.models import AgentTask
from dashboard.serializers import AgentTaskSerializer


class AgentTaskListView(generics.ListAPIView):
    queryset = AgentTask.objects.all()[:100]
    serializer_class = AgentTaskSerializer


class DailyBriefingView(APIView):
    def get(self, request):
        latest = AgentTask.objects.filter(
            agent="strategy_advisor",
            success=True,
        ).first()

        if latest:
            return Response(latest.structured_output)
        return Response({"message": "No briefing available yet"})
