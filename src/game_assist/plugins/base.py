from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np


@dataclass(frozen=True)
class ActionRequest:
    """An input action requested by a plugin and executed by the safe host."""

    plugin_id: str
    token: int
    rule_name: str
    key: str
    hold_ms: int
    audit_message: str
    success_message: str


@dataclass(frozen=True)
class OverlayBox:
    """A plugin-owned rectangle rendered by the host preview."""

    roi: tuple[int, int, int, int]
    label: str
    confidence: float = 1.0
    min_confidence: float = 0.0


@dataclass(frozen=True)
class PluginResult:
    """One plugin's observation for the latest captured frame."""

    plugin_id: str
    summary: str
    percent: float | None = None
    confidence: float | None = None
    streak: int = 0
    action: ActionRequest | None = None
    overlays: tuple[OverlayBox, ...] = ()


@dataclass(frozen=True)
class PluginContext:
    """Read-only results produced by plugins earlier in the current frame."""

    results: Mapping[str, PluginResult]

    def metric(self, plugin_id: str, name: str) -> float | None:
        result = self.results.get(plugin_id)
        if result is None or name not in {"percent", "confidence", "streak"}:
            return None
        value = getattr(result, name)
        return None if value is None else float(value)


class FeaturePlugin(Protocol):
    plugin_id: str
    display_name: str

    def reset_session(self) -> None: ...

    def reset_observations(self) -> None: ...

    def process_frame(self, frame: np.ndarray, now: float, context: PluginContext) -> PluginResult: ...

    def mark_action_completed(self, request: ActionRequest, now: float) -> None: ...


class TimedFeaturePlugin(Protocol):
    """Optional protocol for plugins that need ticks between captured frames."""

    def process_tick(self, now: float, context: PluginContext) -> PluginResult: ...
