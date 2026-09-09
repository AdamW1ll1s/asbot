from __future__ import annotations

from dataclasses import dataclass
import math
import operator
import re

import numpy as np

from ..config import AppConfig
from ..input import parse_key_expression, parse_single_key
from .base import ActionRequest, PluginContext, PluginResult


@dataclass(frozen=True)
class PressCommand:
    key: str
    hold_ms: int = 50


@dataclass(frozen=True)
class WaitCommand:
    duration_ms: int


@dataclass(frozen=True)
class KeyStateCommand:
    key: str
    down: bool


@dataclass(frozen=True)
class MouseMoveCommand:
    x: int
    y: int


@dataclass(frozen=True)
class MouseButtonCommand:
    button: str
    down: bool
    x: int
    y: int


@dataclass(frozen=True)
class MouseWheelCommand:
    delta: int
    x: int
    y: int
    horizontal: bool = False


Command = PressCommand | WaitCommand | KeyStateCommand | MouseMoveCommand | MouseButtonCommand | MouseWheelCommand
MOUSE_BUTTONS = {"left", "right", "middle", "x1", "x2"}


@dataclass(frozen=True)
class Condition:
    plugin_id: str
    metric: str
    operator: str
    value: float

    def matches(self, context: PluginContext) -> bool:
        actual = context.metric(self.plugin_id, self.metric)
        if actual is None:
            return False
        comparisons = {
            "<": operator.lt,
            "<=": operator.le,
            "==": operator.eq,
            ">=": operator.ge,
            ">": operator.gt,
        }
        return comparisons[self.operator](actual, self.value)


@dataclass(frozen=True)
class Macro:
    name: str
    trigger: str
    interval_ms: int | None
    conditions: tuple[Condition, ...]
    repeat: int | None
    commands: tuple[Command, ...]


@dataclass
class MacroRuntime:
    active: bool = False
    started: bool = False
    command_index: int = 0
    completed_repeats: int = 0
    waiting_until: float | None = None
    next_trigger_at: float | None = None


_DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)(ms|s)?$", re.IGNORECASE)


def parse_duration(value: str, *, minimum_ms: int = 1) -> int:
    match = _DURATION_PATTERN.fullmatch(value.strip())
    if match is None:
        raise ValueError(f"无效时间：{value}（示例：250ms 或 2s）")
    amount = float(match.group(1))
    milliseconds = round(amount * (1000 if (match.group(2) or "ms").lower() == "s" else 1))
    if not minimum_ms <= milliseconds <= 3_600_000:
        raise ValueError(f"时间必须在 {minimum_ms}ms 到 1h 之间：{value}")
    return milliseconds


def parse_script(script: str) -> tuple[Macro, ...]:
    """Parse the deliberately small, non-executable AutoKey DSL."""
    macros: list[Macro] = []
    current: dict[str, object] | None = None
    names: set[str] = set()

    def finish(line_number: int) -> None:
        nonlocal current
        if current is None:
            raise ValueError(f"第 {line_number} 行：end 前没有 macro")
        commands = tuple(current["commands"])
        if not commands:
            raise ValueError(f"宏 {current['name']!r} 至少需要一个 press 或 wait")
        macros.append(
            Macro(
                name=str(current["name"]),
                trigger=str(current["trigger"]),
                interval_ms=current["interval_ms"],
                conditions=tuple(current["conditions"]),
                repeat=current["repeat"],
                commands=commands,
            )
        )
        current = None

    for line_number, raw_line in enumerate(script.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(";"):
            continue
        parts = line.split()
        keyword = parts[0].lower()
        if keyword == "macro":
            if current is not None:
                raise ValueError(f"第 {line_number} 行：上一个 macro 缺少 end")
            name = line[len(parts[0]) :].strip()
            if not name:
                raise ValueError(f"第 {line_number} 行：macro 需要名称")
            if name in names:
                raise ValueError(f"第 {line_number} 行：宏名称重复：{name}")
            names.add(name)
            current = {
                "name": name,
                "trigger": "start",
                "interval_ms": None,
                "conditions": [],
                "repeat": 1,
                "commands": [],
            }
            continue
        if keyword == "end":
            finish(line_number)
            continue
        if current is None:
            raise ValueError(f"第 {line_number} 行：命令必须写在 macro 与 end 之间")
        commands: list[Command] = current["commands"]
        if keyword == "trigger":
            if commands:
                raise ValueError(f"第 {line_number} 行：trigger 必须写在动作之前")
            if len(parts) == 2 and parts[1].lower() == "start":
                current["trigger"] = "start"
                current["interval_ms"] = None
            elif len(parts) == 3 and parts[1].lower() in {"every", "interval"}:
                current["trigger"] = "interval"
                current["interval_ms"] = parse_duration(parts[2], minimum_ms=50)
            else:
                raise ValueError(f"第 {line_number} 行：trigger 仅支持 start 或 every <时间>")
        elif keyword in {"when", "if"}:
            if commands:
                raise ValueError(f"第 {line_number} 行：when 必须写在动作之前")
            expression = parts[1:]
            if len(expression) == 1 and expression[0].lower() == "always":
                current["conditions"] = []
                continue
            if len(expression) % 4 != 3:
                raise ValueError(f"第 {line_number} 行：条件格式应为 plugin.metric <数值>，可用 and 连接")
            parsed: list[Condition] = []
            for offset in range(0, len(expression), 4):
                if offset and expression[offset - 1].lower() != "and":
                    raise ValueError(f"第 {line_number} 行：多个条件只能使用 and")
                metric_ref, comparison, raw_value = expression[offset : offset + 3]
                if "." not in metric_ref or comparison not in {"<", "<=", "==", ">=", ">"}:
                    raise ValueError(f"第 {line_number} 行：无效条件：{' '.join(expression)}")
                plugin_id, metric = metric_ref.rsplit(".", 1)
                if metric not in {"percent", "confidence", "streak"}:
                    raise ValueError(f"第 {line_number} 行：不支持的指标：{metric}")
                try:
                    value = float(raw_value)
                except ValueError as error:
                    raise ValueError(f"第 {line_number} 行：条件值必须是数字") from error
                if not math.isfinite(value):
                    raise ValueError(f"第 {line_number} 行：条件值必须是有限数字")
                parsed.append(Condition(plugin_id, metric, comparison, value))
            current["conditions"] = parsed
        elif keyword == "repeat":
            if commands or len(parts) != 2:
                raise ValueError(f"第 {line_number} 行：repeat 必须写在动作之前")
            if parts[1].lower() in {"forever", "infinite"}:
                current["repeat"] = None
            else:
                try:
                    repeat = int(parts[1])
                except ValueError as error:
                    raise ValueError(f"第 {line_number} 行：repeat 必须是正整数或 forever") from error
                if not 1 <= repeat <= 10_000:
                    raise ValueError(f"第 {line_number} 行：repeat 必须在 1 到 10000 之间")
                current["repeat"] = repeat
        elif keyword == "press":
            if len(parts) not in {2, 4} or (len(parts) == 4 and parts[2].lower() != "hold"):
                raise ValueError(f"第 {line_number} 行：press 格式为 press <按键> [hold <时间>]")
            key = parts[1].upper()
            parse_key_expression(key)
            hold_ms = 50 if len(parts) == 2 else parse_duration(parts[3])
            commands.append(PressCommand(key, hold_ms))
        elif keyword in {"key_down", "key_up"}:
            if len(parts) != 2:
                raise ValueError(f"第 {line_number} 行：{keyword} 格式为 {keyword} <按键>")
            key = parts[1].upper()
            parse_single_key(key)
            commands.append(KeyStateCommand(key, keyword == "key_down"))
        elif keyword == "move":
            if len(parts) != 3:
                raise ValueError(f"第 {line_number} 行：move 格式为 move <x> <y>")
            commands.append(MouseMoveCommand(_coordinate(parts[1], line_number), _coordinate(parts[2], line_number)))
        elif keyword in {"mouse_down", "mouse_up"}:
            if len(parts) != 4 or parts[1].lower() not in MOUSE_BUTTONS:
                raise ValueError(f"第 {line_number} 行：{keyword} 格式为 {keyword} <left/right/middle/x1/x2> <x> <y>")
            commands.append(
                MouseButtonCommand(
                    parts[1].lower(),
                    keyword == "mouse_down",
                    _coordinate(parts[2], line_number),
                    _coordinate(parts[3], line_number),
                )
            )
        elif keyword in {"wheel", "hwheel"}:
            if len(parts) != 4:
                raise ValueError(f"第 {line_number} 行：{keyword} 格式为 {keyword} <增量> <x> <y>")
            try:
                delta = int(parts[1])
            except ValueError as error:
                raise ValueError(f"第 {line_number} 行：滚轮增量必须是整数") from error
            if not -12000 <= delta <= 12000 or delta == 0:
                raise ValueError(f"第 {line_number} 行：滚轮增量必须在 -12000 到 12000 之间且不能为 0")
            commands.append(
                MouseWheelCommand(
                    delta,
                    _coordinate(parts[2], line_number),
                    _coordinate(parts[3], line_number),
                    keyword == "hwheel",
                )
            )
        elif keyword == "wait":
            if len(parts) != 2:
                raise ValueError(f"第 {line_number} 行：wait 格式为 wait <时间>")
            commands.append(WaitCommand(parse_duration(parts[1])))
        else:
            raise ValueError(f"第 {line_number} 行：未知命令：{parts[0]}")

    if current is not None:
        raise ValueError(f"宏 {current['name']!r} 缺少 end")
    if not macros:
        raise ValueError("脚本至少需要一个 macro")
    if len(macros) > 100 or sum(len(macro.commands) for macro in macros) > 10_000:
        raise ValueError("脚本过大：最多 100 个宏、10000 条动作")
    return tuple(macros)


def _coordinate(value: str, line_number: int) -> int:
    try:
        coordinate = int(value)
    except ValueError as error:
        raise ValueError(f"第 {line_number} 行：鼠标坐标必须是整数") from error
    if not -32768 <= coordinate <= 32767:
        raise ValueError(f"第 {line_number} 行：鼠标坐标超出支持范围")
    return coordinate


DEFAULT_SCRIPT = """# 启动宿主后执行一次按键序列
macro 示例连招
trigger start
when always
repeat 1
press 1
wait 300ms
press 2 hold 80ms
end

# 定时执行；需要时删除行首的 #
# macro 定时技能
# trigger every 5s
# repeat forever
# press 3
# wait 1s
# end
"""


class AutoKeyPlugin:
    plugin_id = "auto_key"
    display_name = "自动按键"

    def __init__(self, config: AppConfig) -> None:
        settings = config.plugin_settings(self.plugin_id)
        self.script = str(settings.get("script", DEFAULT_SCRIPT))
        self.macros = parse_script(self.script)
        self.runtime = [MacroRuntime() for _ in self.macros]
        self._pending: dict[int, tuple[int, int]] = {}

    def reset_session(self) -> None:
        self.runtime = [MacroRuntime() for _ in self.macros]
        self._pending.clear()

    def reset_observations(self) -> None:
        # Cancel the current sequence after focus loss; interval schedules remain.
        self._pending.clear()
        for state in self.runtime:
            state.active = False
            state.command_index = 0
            state.completed_repeats = 0
            state.waiting_until = None

    def process_frame(self, frame: np.ndarray, now: float, context: PluginContext) -> PluginResult:
        return self.process_tick(now, context)

    def process_tick(self, now: float, context: PluginContext) -> PluginResult:
        for macro_index, (macro, state) in enumerate(zip(self.macros, self.runtime)):
            request = self._step_macro(macro_index, macro, state, now, context)
            if request is not None:
                return PluginResult(self.plugin_id, f"Macro {macro.name} ready", action=request)
        active = next((macro.name for macro, state in zip(self.macros, self.runtime) if state.active), None)
        summary = f"Macro {active} running" if active else f"{len(self.macros)} macros ready"
        return PluginResult(self.plugin_id, summary)

    def _step_macro(
        self,
        macro_index: int,
        macro: Macro,
        state: MacroRuntime,
        now: float,
        context: PluginContext,
    ) -> ActionRequest | None:
        if not state.active:
            if macro.trigger == "interval" and state.next_trigger_at is None:
                state.next_trigger_at = now + macro.interval_ms / 1000
                return None
            due = (macro.trigger == "start" and not state.started) or (
                macro.trigger == "interval" and now >= state.next_trigger_at
            )
            if not due or not all(condition.matches(context) for condition in macro.conditions):
                if due and macro.trigger == "interval" and macro.interval_ms is not None:
                    state.next_trigger_at = now + macro.interval_ms / 1000
                return None
            state.active = True
            state.started = True

        while state.active:
            if state.waiting_until is not None:
                if now < state.waiting_until:
                    return None
                state.waiting_until = None
            if state.command_index >= len(macro.commands):
                state.completed_repeats += 1
                if macro.repeat is None or state.completed_repeats < macro.repeat:
                    state.command_index = 0
                    continue
                state.active = False
                state.command_index = 0
                state.completed_repeats = 0
                if macro.trigger == "interval" and macro.interval_ms is not None:
                    state.next_trigger_at = now + macro.interval_ms / 1000
                return None
            command = macro.commands[state.command_index]
            if isinstance(command, WaitCommand):
                state.command_index += 1
                state.waiting_until = now + command.duration_ms / 1000
                return None
            token = macro_index * 100_000 + state.command_index
            pending = self._pending.get(token)
            if pending is None:
                self._pending[token] = (macro_index, state.command_index)
            action_type = "key_tap"
            key = ""
            hold_ms = 0
            x = y = None
            button = None
            wheel_delta = 0
            description = ""
            if isinstance(command, PressCommand):
                key, hold_ms, description = command.key, command.hold_ms, f"按键 {command.key}"
            elif isinstance(command, KeyStateCommand):
                key = command.key
                action_type = "key_down" if command.down else "key_up"
                description = f"{'按下' if command.down else '释放'} {command.key}"
            elif isinstance(command, MouseMoveCommand):
                action_type, x, y = "mouse_move", command.x, command.y
                description = f"移动鼠标到 ({x}, {y})"
            elif isinstance(command, MouseButtonCommand):
                action_type = "mouse_down" if command.down else "mouse_up"
                x, y, button = command.x, command.y, command.button
                description = f"鼠标 {button} {'按下' if command.down else '释放'}"
            elif isinstance(command, MouseWheelCommand):
                action_type = "mouse_hwheel" if command.horizontal else "mouse_wheel"
                x, y, wheel_delta = command.x, command.y, command.delta
                description = f"鼠标滚轮 {command.delta}"
            else:  # pragma: no cover - parser only creates the command types above
                raise TypeError(f"Unsupported macro command: {command!r}")
            return ActionRequest(
                plugin_id=self.plugin_id,
                token=token,
                rule_name=macro.name,
                key=key,
                hold_ms=hold_ms,
                audit_message=f"插件 {self.display_name} | 宏 {macro.name} | {description}",
                success_message=f"自动按键 · {macro.name} · {description}",
                action_type=action_type,
                x=x,
                y=y,
                button=button,
                wheel_delta=wheel_delta,
            )
        return None

    def mark_action_completed(self, request: ActionRequest, now: float) -> None:
        pending = self._pending.pop(request.token, None)
        if pending is None:
            return
        macro_index, command_index = pending
        state = self.runtime[macro_index]
        if state.command_index == command_index:
            state.command_index += 1
