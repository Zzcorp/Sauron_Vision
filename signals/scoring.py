"""Composite signal scoring — weights multiple sub-scores."""


def calculate_composite_score(sub_scores: dict) -> float:
    """
    Calculate weighted composite score from sub-scores.
    Each sub-score is 0.0 to 1.0.
    """
    weights = {
        "technical": 0.30,
        "fundamental": 0.20,
        "sentiment": 0.15,
        "macro": 0.20,
        "flow": 0.15,
    }

    total_weight = 0.0
    weighted_sum = 0.0

    for key, score in sub_scores.items():
        weight = weights.get(key, 0.10)
        weighted_sum += score * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0

    return round(weighted_sum / total_weight, 4)
