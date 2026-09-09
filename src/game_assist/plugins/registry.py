from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from ..config import AppConfig
from .auto_key import AutoKeyPlugin
from .auto_heal import AutoHealPlugin
from .base import FeaturePlugin


@dataclass(frozen=True)
class PluginDescriptor:
    plugin_id: str
    name: str
    description: str
    version: str
    factory: Callable[[AppConfig], FeaturePlugin]


PLUGIN_DESCRIPTORS = (
    PluginDescriptor(
        plugin_id="auto_heal",
        name="自动喝血",
        description="识别玩家血条，在连续低血量且置信度达标时执行治疗动作。",
        version="1.0.0",
        factory=AutoHealPlugin,
    ),
    PluginDescriptor(
        plugin_id="auto_key",
        name="自动按键",
        description="录制或编排键盘、鼠标、等待、触发条件和循环。",
        version="1.1.0",
        factory=AutoKeyPlugin,
    ),
)


def build_enabled_plugins(config: AppConfig) -> list[FeaturePlugin]:
    return [
        descriptor.factory(config)
        for descriptor in PLUGIN_DESCRIPTORS
        if config.plugin_enabled(descriptor.plugin_id)
    ]
