from dataclasses import replace
from pathlib import Path
import threading
from types import SimpleNamespace

from game_assist.config import load_config
from game_assist.plugins import ActionRequest
from game_assist.runner import AutomationRunner


class FakeKeyboard:
    def __init__(self, results: list[bool]) -> None:
        self.results = iter(results)
        self.taps: list[str] = []

    def tap(self, key: str, duration_ms: int, cancelled: threading.Event) -> bool:
        self.taps.append(key)
        return next(self.results)

    def release_all(self) -> None:
        pass


class FakePlugin:
    plugin_id = "test_plugin"
    display_name = "Test plugin"

    def __init__(self) -> None:
        self.completed = 0

    def reset_session(self) -> None:
        pass

    def reset_observations(self) -> None:
        pass

    def process_frame(self, frame, now):
        raise NotImplementedError

    def mark_action_completed(self, request: ActionRequest, now: float) -> None:
        self.completed += 1


def _request() -> ActionRequest:
    return ActionRequest("test_plugin", 0, "test", "5", 50, "test audit", "test success")


def test_cancelled_action_is_not_reported_to_plugin(monkeypatch, tmp_path: Path) -> None:
    config = load_config("config/profile.example.yaml")
    config = replace(
        config,
        health_bar=replace(config.health_bar, consecutive_frames=1),
        rules=replace(config.rules, cooldown_ms=60_000),
    )
    keyboard = FakeKeyboard([False])
    plugin = FakePlugin()
    runner = AutomationRunner(config, keyboard=keyboard, plugins=[plugin])  # type: ignore[arg-type,list-item]
    monkeypatch.setattr("game_assist.runner.ACTION_LOG_PATH", tmp_path / "actions.log")

    runner._execute_action(_request())

    assert keyboard.taps == ["5"]
    assert plugin.completed == 0
    assert "已取消" in runner.last_event


def test_completed_action_is_reported_to_owning_plugin(monkeypatch, tmp_path: Path) -> None:
    config = load_config("config/profile.example.yaml")
    config = replace(
        config,
        health_bar=replace(config.health_bar, consecutive_frames=1),
        rules=replace(config.rules, cooldown_ms=60_000),
    )
    keyboard = FakeKeyboard([True])
    plugin = FakePlugin()
    runner = AutomationRunner(config, keyboard=keyboard, plugins=[plugin])  # type: ignore[arg-type,list-item]
    monkeypatch.setattr("game_assist.runner.ACTION_LOG_PATH", tmp_path / "actions.log")

    runner._execute_action(_request())

    assert keyboard.taps == ["5"]
    assert plugin.completed == 1
    assert runner.last_event == "test success"


def test_mouse_action_uses_current_client_origin(monkeypatch, tmp_path: Path) -> None:
    class FakeInput(FakeKeyboard):
        def __init__(self) -> None:
            super().__init__([])
            self.actions: list[tuple[str, tuple[int, int] | None]] = []

        def perform(self, action_type: str, **kwargs) -> bool:
            self.actions.append((action_type, kwargs["client_origin"]))
            return True

    config = load_config("config/profile.example.yaml")
    executor = FakeInput()
    plugin = FakePlugin()
    runner = AutomationRunner(config, keyboard=executor, plugins=[plugin])  # type: ignore[arg-type,list-item]
    monkeypatch.setattr("game_assist.runner.ACTION_LOG_PATH", tmp_path / "actions.log")
    monkeypatch.setattr("game_assist.runner.client_rect", lambda hwnd: SimpleNamespace(left=100, top=200))
    request = ActionRequest(
        "test_plugin", 1, "mouse", "", 0, "mouse audit", "mouse success",
        action_type="mouse_move", x=12, y=34,
    )

    runner._execute_action(request, hwnd=99)

    assert executor.actions == [("mouse_move", (100, 200))]
    assert plugin.completed == 1
