from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WindowConfig:
    title_contains: str
    require_foreground: bool


@dataclass(frozen=True)
class HealthBarConfig:
    roi: tuple[int, int, int, int]
    hsv_lower: tuple[int, int, int]
    hsv_upper: tuple[int, int, int]
    column_coverage: float
    min_confidence: float


@dataclass(frozen=True)
class RuleConfig:
    heal_below_percent: float
    heal_key: str
    cooldown_ms: int


@dataclass(frozen=True)
class AppConfig:
    window: WindowConfig
    toggle_hotkey: str
    emergency_stop_hotkey: str
    poll_interval_ms: int
    save_debug_frame: bool
    health_bar: HealthBarConfig
    rules: RuleConfig


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"Missing configuration value: {key}")
    return mapping[key]


def _as_tuple(value: Any, size: int, name: str) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != size:
        raise ValueError(f"{name} must be a list of {size} integers")
    return tuple(int(item) for item in value)


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open(encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    try:
        window = raw["window"]
        hotkeys = raw["hotkeys"]
        capture = raw["capture"]
        health = raw["health_bar"]
        rules = raw["rules"]
    except KeyError as error:
        raise ValueError(f"Missing configuration section: {error.args[0]}") from error

    config = AppConfig(
        window=WindowConfig(
            title_contains=str(_required(window, "title_contains")),
            require_foreground=bool(window.get("require_foreground", True)),
        ),
        toggle_hotkey=str(_required(hotkeys, "toggle")).upper(),
        emergency_stop_hotkey=str(_required(hotkeys, "emergency_stop")).upper(),
        poll_interval_ms=int(_required(capture, "poll_interval_ms")),
        save_debug_frame=bool(capture.get("save_debug_frame", False)),
        health_bar=HealthBarConfig(
            roi=_as_tuple(_required(health, "roi"), 4, "health_bar.roi"),
            hsv_lower=_as_tuple(_required(health, "hsv_lower"), 3, "health_bar.hsv_lower"),
            hsv_upper=_as_tuple(_required(health, "hsv_upper"), 3, "health_bar.hsv_upper"),
            column_coverage=float(_required(health, "column_coverage")),
            min_confidence=float(_required(health, "min_confidence")),
        ),
        rules=RuleConfig(
            heal_below_percent=float(_required(rules, "heal_below_percent")),
            heal_key=str(_required(rules, "heal_key")).upper(),
            cooldown_ms=int(_required(rules, "cooldown_ms")),
        ),
    )
    if config.poll_interval_ms < 20:
        raise ValueError("capture.poll_interval_ms must be at least 20")
    if not 0 < config.health_bar.column_coverage <= 1:
        raise ValueError("health_bar.column_coverage must be in (0, 1]")
    return config
