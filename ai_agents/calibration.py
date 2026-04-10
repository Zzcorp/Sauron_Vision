"""Agent calibration — track prediction accuracy over time."""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_prediction_model():
    """Lazy import to avoid circular imports."""
    from ai_agents.models import AgentPrediction
    return AgentPrediction


class CalibrationTracker:
    """Track and report agent calibration metrics."""

    def get_agent_accuracy(self, agent_name, lookback_days=90):
        """Get accuracy metrics for an agent."""
        from datetime import timedelta
        AgentPrediction = _get_prediction_model()
        cutoff = timezone.now() - timedelta(days=lookback_days)

        predictions = AgentPrediction.objects.filter(
            agent=agent_name,
            created_at__gte=cutoff,
            was_correct__isnull=False,
        )

        total = predictions.count()
        if total == 0:
            return {'agent': agent_name, 'total': 0, 'note': 'no evaluated predictions'}

        correct = predictions.filter(was_correct=True).count()
        accuracy = correct / total

        # Accuracy by prediction type
        by_type = {}
        for pt in predictions.values_list('prediction_type', flat=True).distinct():
            type_preds = predictions.filter(prediction_type=pt)
            type_total = type_preds.count()
            type_correct = type_preds.filter(was_correct=True).count()
            by_type[pt] = {
                'total': type_total,
                'correct': type_correct,
                'accuracy': round(type_correct / type_total, 4) if type_total > 0 else 0,
            }

        # Calibration: for each confidence bucket, how often was it correct?
        calibration = {}
        for bucket in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
            bucket_preds = predictions.filter(
                confidence__gte=bucket - 0.05,
                confidence__lt=bucket + 0.05,
            )
            bucket_total = bucket_preds.count()
            if bucket_total > 0:
                bucket_correct = bucket_preds.filter(was_correct=True).count()
                calibration[str(bucket)] = {
                    'predicted_confidence': bucket,
                    'actual_accuracy': round(bucket_correct / bucket_total, 4),
                    'n': bucket_total,
                }

        return {
            'agent': agent_name,
            'total_predictions': total,
            'correct': correct,
            'accuracy': round(accuracy, 4),
            'by_type': by_type,
            'calibration': calibration,
            'lookback_days': lookback_days,
        }

    def get_all_agents_accuracy(self):
        """Get accuracy summary for all agents."""
        AgentPrediction = _get_prediction_model()
        agents = AgentPrediction.objects.values_list('agent', flat=True).distinct()
        return {agent: self.get_agent_accuracy(agent) for agent in agents}

    def suggest_confidence_adjustment(self, agent_name):
        """Suggest confidence weight adjustment based on calibration."""
        metrics = self.get_agent_accuracy(agent_name)
        if metrics.get('total_predictions', 0) < 20:
            return {'adjustment': 1.0, 'reason': 'insufficient data'}

        accuracy = metrics['accuracy']

        # If agent is overconfident (high confidence, low accuracy), reduce weight
        # If underconfident (low confidence, high accuracy), increase weight
        if accuracy < 0.4:
            adjustment = 0.7
            reason = f"Low accuracy ({accuracy:.1%}), reducing confidence weight"
        elif accuracy < 0.5:
            adjustment = 0.85
            reason = f"Below average accuracy ({accuracy:.1%})"
        elif accuracy > 0.8:
            adjustment = 1.3
            reason = f"Excellent accuracy ({accuracy:.1%})"
        elif accuracy > 0.7:
            adjustment = 1.15
            reason = f"High accuracy ({accuracy:.1%}), increasing confidence weight"
        else:
            adjustment = 1.0
            reason = f"Average accuracy ({accuracy:.1%}), no adjustment"

        return {'adjustment': round(adjustment, 3), 'reason': reason, 'accuracy': accuracy}


def log_prediction(agent, prediction_type, predicted_value, instrument_symbol='', confidence=0.5):
    """Log a prediction for future calibration."""
    AgentPrediction = _get_prediction_model()
    return AgentPrediction.objects.create(
        agent=agent,
        prediction_type=prediction_type,
        predicted_value=str(predicted_value),
        instrument_symbol=instrument_symbol,
        confidence=confidence,
    )


def evaluate_prediction(prediction_id, actual_value, was_correct):
    """Evaluate a previous prediction."""
    AgentPrediction = _get_prediction_model()
    pred = AgentPrediction.objects.get(id=prediction_id)
    pred.actual_value = str(actual_value)
    pred.was_correct = was_correct
    pred.evaluated_at = timezone.now()
    pred.save()
    return pred
