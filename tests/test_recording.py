import pytest

from game_assist.plugins.auto_key import parse_script
from game_assist.recording import RecordedEvent, recorded_events_to_script


def test_recorded_events_convert_to_valid_macro_script() -> None:
    events = (
        RecordedEvent(0, "key_down", key="W"),
        RecordedEvent(85, "move", x=40, y=50),
        RecordedEvent(100, "mouse_down", x=40, y=50, button="left"),
        RecordedEvent(140, "mouse_up", x=40, y=50, button="left"),
        RecordedEvent(200, "key_up", key="W"),
    )

    script = recorded_events_to_script(events, "movement")

    macro = parse_script(script)[0]
    assert macro.name == "movement"
    assert len(macro.commands) == 9
    assert "wait 85ms" in script


def test_empty_recording_cannot_be_exported() -> None:
    with pytest.raises(ValueError):
        recorded_events_to_script(())
