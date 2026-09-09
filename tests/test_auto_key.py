from dataclasses import replace

import numpy as np
import pytest

from game_assist.config import PluginConfig, load_config
from game_assist.plugins.auto_key import (
    AutoKeyPlugin,
    KeyStateCommand,
    MouseButtonCommand,
    MouseMoveCommand,
    MouseWheelCommand,
    PressCommand,
    WaitCommand,
    parse_script,
)
from game_assist.plugins.base import PluginContext, PluginResult


def _plugin(script: str) -> AutoKeyPlugin:
    config = load_config("config/profile.example.yaml")
    plugins = tuple(item for item in config.plugins if item.plugin_id != "auto_key")
    config = replace(config, plugins=(*plugins, PluginConfig("auto_key", True, {"script": script})))
    return AutoKeyPlugin(config)


def test_parses_trigger_condition_repeat_and_commands() -> None:
    macro = parse_script(
        """macro combat
trigger every 2s
when auto_heal.percent < 30 and auto_heal.confidence >= 0.8
repeat 3
press CTRL+1 hold 80ms
wait 250ms
end
"""
    )[0]

    assert macro.interval_ms == 2000
    assert macro.repeat == 3
    assert macro.conditions[0].metric == "percent"
    assert macro.commands == (PressCommand("CTRL+1", 80), WaitCommand(250))


@pytest.mark.parametrize(
    "script",
    [
        "",
        "press 1",
        "macro x\npress UNKNOWN\nend",
        "macro x\nrepeat 0\npress 1\nend",
        "macro x\nwhen auto_heal.unknown > 1\npress 1\nend",
        "macro x\npress 1",
    ],
)
def test_rejects_invalid_scripts(script: str) -> None:
    with pytest.raises(ValueError):
        parse_script(script)


def test_non_blocking_wait_and_repeat_advance_only_after_completed_action() -> None:
    plugin = _plugin(
        """macro combo
trigger start
repeat 2
press 1
wait 100ms
press 2
end
"""
    )
    context = PluginContext({})

    first = plugin.process_tick(0.0, context).action
    assert first is not None and first.key == "1"
    # Without completion confirmation, the same action remains pending.
    assert plugin.process_tick(0.01, context).action.token == first.token
    plugin.mark_action_completed(first, 0.01)
    assert plugin.process_tick(0.02, context).action is None
    assert plugin.process_tick(0.11, context).action is None
    second = plugin.process_tick(0.13, context).action
    assert second is not None and second.key == "2"
    plugin.mark_action_completed(second, 0.13)
    repeated = plugin.process_tick(0.14, context).action
    assert repeated is not None and repeated.key == "1"


def test_start_trigger_waits_until_plugin_condition_is_true() -> None:
    plugin = _plugin(
        """macro emergency
trigger start
when auto_heal.percent < 30
press 5
end
"""
    )

    assert plugin.process_tick(0.0, PluginContext({})).action is None
    high = PluginResult("auto_heal", "high", percent=80, confidence=0.9)
    assert plugin.process_tick(0.1, PluginContext({"auto_heal": high})).action is None
    low = PluginResult("auto_heal", "low", percent=20, confidence=0.9)
    assert plugin.process_tick(0.2, PluginContext({"auto_heal": low})).action.key == "5"


def test_interval_trigger_waits_for_first_interval() -> None:
    plugin = _plugin("macro timer\ntrigger every 500ms\npress 1\nend")
    context = PluginContext({})

    assert plugin.process_tick(10.0, context).action is None
    assert plugin.process_tick(10.49, context).action is None
    assert plugin.process_tick(10.5, context).action.key == "1"


def test_process_frame_uses_same_timer_state_machine() -> None:
    plugin = _plugin("macro once\npress A\nend")
    frame = np.zeros((1, 1, 3), dtype=np.uint8)

    assert plugin.process_frame(frame, 0.0, PluginContext({})).action.key == "A"


def test_parses_recorded_keyboard_and_mouse_commands() -> None:
    macro = parse_script(
        """macro recorded
key_down W
move 120 240
mouse_down left 120 240
wheel -120 120 240
mouse_up left 120 240
key_up W
end
"""
    )[0]

    assert macro.commands == (
        KeyStateCommand("W", True),
        MouseMoveCommand(120, 240),
        MouseButtonCommand("left", True, 120, 240),
        MouseWheelCommand(-120, 120, 240),
        MouseButtonCommand("left", False, 120, 240),
        KeyStateCommand("W", False),
    )


def test_mouse_command_becomes_mouse_action_request() -> None:
    plugin = _plugin("macro click\nmove 12 34\nend")

    action = plugin.process_tick(0.0, PluginContext({})).action

    assert action is not None
    assert action.action_type == "mouse_move"
    assert (action.x, action.y) == (12, 34)
