from game_assist.rules import should_trigger_health_rule


def test_triggers_only_below_threshold() -> None:
    assert should_trigger_health_rule(29.9, 30.0, 0.8, 0.7)
    assert not should_trigger_health_rule(30.0, 30.0, 0.8, 0.7)
    assert not should_trigger_health_rule(30.1, 30.0, 0.8, 0.7)


def test_requires_minimum_confidence() -> None:
    assert should_trigger_health_rule(20.0, 30.0, 0.7, 0.7)
    assert not should_trigger_health_rule(20.0, 30.0, 0.69, 0.7)
