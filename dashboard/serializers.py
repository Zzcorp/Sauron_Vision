"""DRF serializers for the dashboard API."""
from rest_framework import serializers
from instruments.models import Instrument
from market_data.models import LiveQuote, EconomicEvent
from signals.models import Signal
from strategies.models import Strategy
from portfolio.models import Portfolio, Position, PortfolioSnapshot
from ai_agents.models import AgentTask


class InstrumentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        # Explicit allowlist — never "__all__". The `metadata` JSON field carries
        # per-instrument broker routing/contract config (e.g. metadata["ibkr"])
        # and must not be exposed through the API.
        fields = [
            "id", "symbol", "name", "asset_class", "exchange", "currency",
            "sector", "country", "is_active", "is_watchlist", "trading_hours",
            "created_at", "updated_at",
        ]


class LiveQuoteSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument.symbol")
    name = serializers.CharField(source="instrument.name")

    class Meta:
        model = LiveQuote
        fields = ["symbol", "name", "bid", "ask", "last", "change_pct", "volume", "updated_at"]


class EconomicEventSerializer(serializers.ModelSerializer):
    class Meta:
        model = EconomicEvent
        fields = "__all__"


class SignalSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument.symbol")

    class Meta:
        model = Signal
        fields = "__all__"


class StrategySerializer(serializers.ModelSerializer):
    class Meta:
        model = Strategy
        fields = "__all__"


class PortfolioSerializer(serializers.ModelSerializer):
    class Meta:
        model = Portfolio
        fields = "__all__"


class PositionSerializer(serializers.ModelSerializer):
    symbol = serializers.CharField(source="instrument.symbol")

    class Meta:
        model = Position
        fields = "__all__"


class SnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = PortfolioSnapshot
        fields = "__all__"


class AgentTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model = AgentTask
        fields = "__all__"
