from __future__ import annotations

import numpy as np

from ..config import AppConfig, HealthBarConfig
from ..health import HealthBarDetector
from ..rules import HealthRuleEvaluator
from .base import ActionRequest, OverlayBox, PluginContext, PluginResult


class AutoHealPlugin:
    """Detect a health bar and request configured healing actions."""

    plugin_id = "auto_heal"
    display_name = "自动喝血"

    def __init__(self, config: AppConfig) -> None:
        self.update_config(config)

    def update_config(self, config: AppConfig) -> None:
        self.config = config
        self.health_config: HealthBarConfig = config.health_bar
        self.detector = HealthBarDetector(config.health_bar)
        self.evaluator = HealthRuleEvaluator(
            (config.rules, *config.additional_rules),
            config.health_bar.min_confidence,
            config.health_bar.consecutive_frames,
        )

    def reset_session(self) -> None:
        self.evaluator.reset_session()

    def reset_observations(self) -> None:
        self.evaluator.reset_observations()

    def process_frame(self, frame: np.ndarray, now: float, context: PluginContext) -> PluginResult:
        reading = self.detector.detect(frame)
        if reading is None:
            self.reset_observations()
            return PluginResult(
                plugin_id=self.plugin_id,
                summary="Health ROI unavailable",
                overlays=(
                    OverlayBox(
                        self.health_config.roi,
                        "Health ROI",
                        confidence=0.0,
                        min_confidence=self.health_config.min_confidence,
                    ),
                ),
            )

        match = self.evaluator.evaluate(reading.percent, reading.confidence, now)
        action = None
        if match is not None:
            rule = match.rule
            audit = (
                f"插件 {self.display_name} | 规则 {rule.name}"
                f" | HP {reading.percent:.1f}% < 阈值 {rule.heal_below_percent:.1f}%"
                f" | 置信度 {reading.confidence:.2f} | 按键 {rule.heal_key}"
            )
            action = ActionRequest(
                plugin_id=self.plugin_id,
                token=match.index,
                rule_name=rule.name,
                key=rule.heal_key,
                hold_ms=rule.hold_ms,
                audit_message=audit,
                success_message=(
                    f"{self.display_name}已触发 {rule.heal_key}"
                    f" · HP {reading.percent:.1f}% < {rule.heal_below_percent:.1f}%"
                ),
            )
        return PluginResult(
            plugin_id=self.plugin_id,
            summary=f"HP {reading.percent:.1f}% | confidence {reading.confidence:.2f}",
            percent=reading.percent,
            confidence=reading.confidence,
            streak=self.evaluator.longest_streak,
            action=action,
            overlays=(
                OverlayBox(
                    self.health_config.roi,
                    "Health ROI",
                    confidence=reading.confidence,
                    min_confidence=self.health_config.min_confidence,
                ),
            ),
        )

    def mark_action_completed(self, request: ActionRequest, now: float) -> None:
        # The token is the stable rule index produced by HealthRuleEvaluator.
        from ..rules import RuleMatch

        rule = self.evaluator.rules[request.token]
        self.evaluator.mark_triggered(RuleMatch(request.token, rule), now)
