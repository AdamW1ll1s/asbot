from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class WindowConfig:
    title_contains: str
    require_foreground: bool
    process_id: int | None = None


@dataclass(frozen=True)
class HealthBarConfig:
    roi: tuple[int, int, int, int]
    hsv_lower: tuple[int, int, int]
    hsv_upper: tuple[int, int, int]
    column_coverage: float
    min_confidence: float
    hsv_ranges: tuple[tuple[tuple[int, int, int], tuple[int, int, int]], ...] = ()
    consecutive_frames: int = 1


@dataclass(frozen=True)
class RuleConfig:
    name: str
    heal_below_percent: float
    heal_key: str
    cooldown_ms: int
    hold_ms: int = 50


@dataclass(frozen=True)
class AppConfig:
    window: WindowConfig
    toggle_hotkey: str
    emergency_stop_hotkey: str
    poll_interval_ms: int
    save_debug_frame: bool
    health_bar: HealthBarConfig
    rules: RuleConfig
    additional_rules: tuple[RuleConfig, ...] = ()


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
            process_id=int(window["process_id"]) if window.get("process_id") else None,
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
            hsv_ranges=tuple((_as_tuple(_required(item, "lower"), 3, "health_bar.hsv_ranges.lower"), _as_tuple(_required(item, "upper"), 3, "health_bar.hsv_ranges.upper")) for item in health.get("hsv_ranges", [])),
            consecutive_frames=int(health.get("consecutive_frames", 1)),
        ),
        rules=_rule_from_mapping(rules, "Heal"),
        additional_rules=tuple(_rule_from_mapping(item, f"Rule {index + 2}") for index, item in enumerate(raw.get("additional_rules", []))),
    )
    if config.poll_interval_ms < 20:
        raise ValueError("capture.poll_interval_ms must be at least 20")
    if not 0 < config.health_bar.column_coverage <= 1:
        raise ValueError("health_bar.column_coverage must be in (0, 1]")
    if config.health_bar.consecutive_frames < 1:
        raise ValueError("health_bar.consecutive_frames must be at least 1")
    return config


def _rule_from_mapping(raw: dict[str, Any], default_name: str) -> RuleConfig:
    return RuleConfig(name=str(raw.get("name", default_name)), heal_below_percent=float(_required(raw, "heal_below_percent")), heal_key=str(_required(raw, "heal_key")).upper(), cooldown_ms=int(_required(raw, "cooldown_ms")), hold_ms=int(raw.get("hold_ms", 50)))


def save_config(path: str | Path, config: AppConfig) -> None:
    """Write a portable YAML profile from the in-memory application settings."""
    raw = {
        "window": {
            "title_contains": config.window.title_contains,
            "require_foreground": config.window.require_foreground,
            **({"process_id": config.window.process_id} if config.window.process_id else {}),
        },
        "hotkeys": {
            "toggle": config.toggle_hotkey,
            "emergency_stop": config.emergency_stop_hotkey,
        },
        "capture": {
            "poll_interval_ms": config.poll_interval_ms,
            "save_debug_frame": config.save_debug_frame,
        },
        "health_bar": {
            "roi": list(config.health_bar.roi),
            "hsv_lower": list(config.health_bar.hsv_lower),
            "hsv_upper": list(config.health_bar.hsv_upper),
            "column_coverage": config.health_bar.column_coverage,
            "min_confidence": config.health_bar.min_confidence,
            "hsv_ranges": [{"lower": list(lower), "upper": list(upper)} for lower, upper in config.health_bar.hsv_ranges],
            "consecutive_frames": config.health_bar.consecutive_frames,
        },
        "rules": {
            "heal_below_percent": config.rules.heal_below_percent,
            "heal_key": config.rules.heal_key,
            "cooldown_ms": config.rules.cooldown_ms,
            "hold_ms": config.rules.hold_ms,
        },
        "additional_rules": [{"name": rule.name, "heal_below_percent": rule.heal_below_percent, "heal_key": rule.heal_key, "cooldown_ms": rule.cooldown_ms, "hold_ms": rule.hold_ms} for rule in config.additional_rules],
    }
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as file:
        yaml.safe_dump(raw, file, allow_unicode=True, sort_keys=False)
