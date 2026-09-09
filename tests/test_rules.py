from game_assist.config import RuleConfig
from game_assist.rules import HealthRuleEvaluator, should_trigger_health_rule


def test_triggers_only_below_threshold() -> None:
    assert should_trigger_health_rule(29.9, 30.0, 0.8, 0.7)
    assert not should_trigger_health_rule(30.0, 30.0, 0.8, 0.7)
    assert not should_trigger_health_rule(30.1, 30.0, 0.8, 0.7)


def test_requires_minimum_confidence() -> None:
    assert should_trigger_health_rule(20.0, 30.0, 0.7, 0.7)
    assert not should_trigger_health_rule(20.0, 30.0, 0.69, 0.7)


def _rule(name: str, threshold: float, cooldown_ms: int = 1000) -> RuleConfig:
    return RuleConfig(name, threshold, "5", cooldown_ms)


def test_consecutive_frames_must_all_be_below_threshold() -> None:
    evaluator = HealthRuleEvaluator((_rule("heal", 30),), 0.7, consecutive_frames=2)

    assert evaluator.evaluate(60, 0.9, now=0.0) is None
    assert evaluator.evaluate(20, 0.9, now=0.1) is None
    assert evaluator.evaluate(20, 0.9, now=0.2) is not None


def test_emergency_rule_wins_and_blocks_broader_rule_during_cooldown() -> None:
    normal = _rule("normal", 30, cooldown_ms=5000)
    emergency = _rule("emergency", 15, cooldown_ms=1000)
    evaluator = HealthRuleEvaluator((normal, emergency), 0.7, consecutive_frames=1)

    first = evaluator.evaluate(10, 0.9, now=0.0)
    assert first is not None and first.rule == emergency
    evaluator.mark_triggered(first, now=0.0)

    assert evaluator.evaluate(10, 0.9, now=0.1) is None
    assert evaluator.evaluate(10, 0.9, now=1.0).rule == emergency


def test_rules_keep_independent_cooldowns() -> None:
    normal = _rule("normal", 30, cooldown_ms=5000)
    emergency = _rule("emergency", 15, cooldown_ms=1000)
    evaluator = HealthRuleEvaluator((normal, emergency), 0.7, consecutive_frames=1)

    first = evaluator.evaluate(20, 0.9, now=0.0)
    assert first is not None and first.rule == normal
    evaluator.mark_triggered(first, now=0.0)

    urgent = evaluator.evaluate(10, 0.9, now=0.1)
    assert urgent is not None and urgent.rule == emergency


def test_low_confidence_resets_debounce() -> None:
    evaluator = HealthRuleEvaluator((_rule("heal", 30),), 0.7, consecutive_frames=2)

    assert evaluator.evaluate(20, 0.9, now=0.0) is None
    assert evaluator.evaluate(20, 0.6, now=0.1) is None
    assert evaluator.evaluate(20, 0.9, now=0.2) is None
