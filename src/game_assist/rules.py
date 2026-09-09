from __future__ import annotations

from dataclasses import dataclass

from .config import RuleConfig


def should_trigger_health_rule(
    percent: float,
    threshold: float,
    confidence: float,
    min_confidence: float,
) -> bool:
    """Return whether a health rule passes its strict threshold and confidence checks."""
    return percent < threshold and confidence >= min_confidence


@dataclass(frozen=True)
class RuleMatch:
    index: int
    rule: RuleConfig


class HealthRuleEvaluator:
    """Debounce health rules and keep an independent cooldown for each action."""

    def __init__(
        self,
        rules: tuple[RuleConfig, ...],
        min_confidence: float,
        consecutive_frames: int,
    ) -> None:
        self.rules = rules
        self.min_confidence = min_confidence
        self.consecutive_frames = consecutive_frames
        self._streaks = [0] * len(rules)
        self._last_triggered_at: dict[int, float] = {}

    def reset_observations(self) -> None:
        self._streaks = [0] * len(self.rules)

    def reset_session(self) -> None:
        self.reset_observations()
        self._last_triggered_at.clear()

    @property
    def longest_streak(self) -> int:
        return max(self._streaks, default=0)

    def evaluate(self, percent: float, confidence: float, now: float) -> RuleMatch | None:
        if confidence < self.min_confidence:
            self.reset_observations()
            return None

        eligible: list[RuleMatch] = []
        for index, rule in enumerate(self.rules):
            if percent < rule.heal_below_percent:
                self._streaks[index] += 1
            else:
                self._streaks[index] = 0
            if self._streaks[index] >= self.consecutive_frames:
                eligible.append(RuleMatch(index, rule))

        if not eligible:
            return None
        # A lower threshold is more specific/urgent. This makes an emergency
        # rule useful even when a broader normal-heal rule also matches.
        selected = min(eligible, key=lambda match: (match.rule.heal_below_percent, match.index))
        last_triggered = self._last_triggered_at.get(selected.index)
        if last_triggered is not None and now - last_triggered < selected.rule.cooldown_ms / 1000:
            return None
        return selected

    def mark_triggered(self, match: RuleMatch, now: float) -> None:
        self._last_triggered_at[match.index] = now
