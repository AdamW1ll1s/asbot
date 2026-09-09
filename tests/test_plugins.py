from dataclasses import replace

import cv2
import numpy as np

from game_assist.config import PluginConfig, load_config
from game_assist.plugins.auto_heal import AutoHealPlugin
from game_assist.plugins.base import PluginContext
from game_assist.plugins.registry import build_enabled_plugins


def test_auto_heal_plugin_owns_detection_debounce_and_cooldown() -> None:
    config = load_config("config/profile.example.yaml")
    config = replace(
        config,
        health_bar=replace(config.health_bar, roi=(0, 0, 100, 20), consecutive_frames=2),
        rules=replace(config.rules, heal_below_percent=30, cooldown_ms=1000),
    )
    frame = np.zeros((20, 100, 3), dtype=np.uint8)
    cv2.rectangle(frame, (0, 0), (19, 19), (0, 0, 255), thickness=-1)
    plugin = AutoHealPlugin(config)

    context = PluginContext({})
    assert plugin.process_frame(frame, now=0.0, context=context).action is None
    request = plugin.process_frame(frame, now=0.1, context=context).action
    assert request is not None
    assert request.plugin_id == "auto_heal"

    plugin.mark_action_completed(request, now=0.1)
    assert plugin.process_frame(frame, now=0.2, context=context).action is None
    assert plugin.process_frame(frame, now=1.1, context=context).action is not None


def test_registry_does_not_build_disabled_plugin() -> None:
    config = load_config("config/profile.example.yaml")
    config = replace(config, plugins=(PluginConfig("auto_heal", enabled=False),))

    assert build_enabled_plugins(config) == []
