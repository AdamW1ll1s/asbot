from __future__ import annotations


def should_trigger_health_rule(
    percent: float,
    threshold: float,
    confidence: float,
    min_confidence: float,
) -> bool:
    """Return whether a health rule passes its strict threshold and confidence checks."""
    return percent < threshold and confidence >= min_confidence
