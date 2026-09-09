from __future__ import annotations

from collections import deque
import logging
from pathlib import Path
import threading
import time

import cv2
import mss
import numpy as np

from .config import AppConfig
from .input import KeyboardExecutor
from .plugins import ActionRequest, FeaturePlugin, PluginContext, PluginResult, build_enabled_plugins
from .windows import activate_window, client_rect, find_window, is_foreground


LOG = logging.getLogger(__name__)
ACTION_LOG_PATH = Path("logs/actions.log")


class AutomationRunner:
    def __init__(
        self,
        config: AppConfig,
        preview_only: bool = False,
        keyboard: KeyboardExecutor | None = None,
        plugins: list[FeaturePlugin] | None = None,
    ) -> None:
        self.config = config
        self.preview_only = preview_only
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._keyboard = keyboard or KeyboardExecutor()
        self._plugins = build_enabled_plugins(config) if plugins is None else plugins
        self.plugin_results: dict[str, PluginResult] = {}
        self._action_lock = threading.Lock()
        self._action_history: deque[str] = deque(maxlen=200)
        self._reading_streak = 0
        self.last_reading: tuple[float, float] | None = None
        self.last_event = "Waiting"
        self.paused_for_focus = False
        self._last_debug_at = 0.0
        self._last_recognition_at = 0.0
        self._preview_lock = threading.Lock()
        self._latest_preview: np.ndarray | None = None
        self._latest_raw: np.ndarray | None = None
        self._preview_revision = 0

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._cancel.clear()
        for plugin in self._plugins:
            plugin.reset_session()
        self.plugin_results.clear()
        self._reading_streak = 0
        self.last_reading = None
        self.last_event = "等待首次识别"
        self.paused_for_focus = False
        self._last_recognition_at = 0.0
        self._thread = threading.Thread(target=self._run, name="automation-runner", daemon=True)
        self._thread.start()
        LOG.info("Automation started")

    def stop(self) -> None:
        self._cancel.set()
        self._keyboard.release_all()
        if not self.last_event.startswith("运行失败"):
            self.last_event = "已停止"
        LOG.info("Automation stopped")

    def update_config(self, config: AppConfig) -> None:
        """Rebuild enabled plugins after live configuration changes."""
        self.config = config
        self._plugins = build_enabled_plugins(self.config)
        for plugin in self._plugins:
            plugin.reset_session()
        self.plugin_results.clear()
        self._reading_streak = 0
        self.last_reading = None
        self._last_recognition_at = 0.0

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def action_history(self) -> tuple[str, ...]:
        with self._action_lock:
            return tuple(self._action_history)

    def _run(self) -> None:
        try:
            hwnd = find_window(self.config.window.title_contains, self.config.window.process_id)
            if hwnd is None:
                self.last_event = "运行失败：找不到目标窗口"
                LOG.error("No visible window contains title: %r", self.config.window.title_contains)
                return
            # Clicking the control-panel Start button necessarily gives the
            # control panel focus. Restore focus to the selected target before
            # enforcing the foreground-only safety rule.
            if not self.preview_only and self.config.window.require_foreground:
                activate_window(hwnd)
            focus_paused = False
            with mss.mss() as screen:
                while not self._cancel.is_set():
                    if not self.preview_only and self.config.window.require_foreground and not is_foreground(hwnd):
                        if not focus_paused:
                            focus_paused = True
                            self.paused_for_focus = True
                            self._reading_streak = 0
                            for plugin in self._plugins:
                                plugin.reset_observations()
                            self._keyboard.release_all()
                            self.last_event = "已暂停 · 等待目标窗口回到前台"
                            LOG.warning("Target window lost focus; automation paused")
                        self._cancel.wait(min(self.config.poll_interval_ms / 1000, 0.25))
                        continue
                    if focus_paused:
                        focus_paused = False
                        self.paused_for_focus = False
                        self.last_event = "目标窗口已恢复 · 继续运行"
                        LOG.info("Target window regained focus; automation resumed")
                    now = time.monotonic()
                    recognition_interval = self.config.recognition_interval_ms / 1000
                    until_next_recognition = recognition_interval - (now - self._last_recognition_at)
                    if until_next_recognition > 0:
                        self._tick_timed_plugins(now)
                        self._cancel.wait(min(self.config.poll_interval_ms / 1000, until_next_recognition))
                        continue
                    rect = client_rect(hwnd)
                    if rect is None:
                        self.last_event = "运行失败：目标客户区不可用"
                        LOG.warning("Target client area is unavailable; stopping")
                        return
                    client_bgr = self._capture(screen, rect.left, rect.top, rect.width, rect.height)
                    self._last_recognition_at = now
                    results: list[PluginResult] = []
                    for plugin in self._plugins:
                        context = PluginContext({result.plugin_id: result for result in results})
                        results.append(plugin.process_frame(client_bgr, now, context))
                    self.plugin_results = {result.plugin_id: result for result in results}
                    health_result = self.plugin_results.get("auto_heal")
                    if health_result and health_result.percent is not None and health_result.confidence is not None:
                        self.last_reading = (health_result.percent, health_result.confidence)
                        self._reading_streak = health_result.streak
                        LOG.info("HP %.1f%% (confidence %.2f)", health_result.percent, health_result.confidence)
                    else:
                        self.last_reading = None
                        self._reading_streak = 0
                    if not self.preview_only:
                        action = next((result.action for result in results if result.action is not None), None)
                        if action is not None:
                            self._execute_action(action)
                    with self._preview_lock:
                        self._latest_preview = self._annotate_frame(client_bgr, results)
                        self._latest_raw = client_bgr.copy()
                        self._preview_revision += 1
                    self._write_debug(client_bgr, results)
        except Exception as error:
            self.last_event = f"运行失败：{error}"
            LOG.exception("Automation failed safely")
        finally:
            self.paused_for_focus = False
            self._keyboard.release_all()
            self._cancel.set()

    def _tick_timed_plugins(self, now: float) -> None:
        """Advance timer-driven plugins without taking another screenshot."""
        for plugin in self._plugins:
            process_tick = getattr(plugin, "process_tick", None)
            if process_tick is None:
                continue
            result = process_tick(now, PluginContext(dict(self.plugin_results)))
            self.plugin_results[result.plugin_id] = result
            if not self.preview_only and result.action is not None:
                self._execute_action(result.action)
                break

    def _execute_action(self, request: ActionRequest) -> None:
        self.last_event = f"{request.plugin_id} · 准备触发 {request.key}"
        LOG.warning("Plugin action requested: %s", request.audit_message)
        try:
            completed = self._keyboard.tap(request.key, duration_ms=request.hold_ms, cancelled=self._cancel)
        except Exception as error:
            self._record_action(f"{request.audit_message} | 失败：{error}")
            raise
        if completed:
            plugin = next((item for item in self._plugins if item.plugin_id == request.plugin_id), None)
            if plugin is None:
                raise RuntimeError(f"Action references missing plugin: {request.plugin_id}")
            plugin.mark_action_completed(request, time.monotonic())
            self.last_event = request.success_message
            self._record_action(f"{request.audit_message} | 已发送")
        else:
            self.last_event = f"{request.plugin_id} · 已取消 {request.key}"
            self._record_action(f"{request.audit_message} | 已取消或未完成")

    def _record_action(self, event: str) -> None:
        line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} | {event}"
        with self._action_lock:
            self._action_history.append(line)
        LOG.warning("Action result: %s", line)
        try:
            ACTION_LOG_PATH.parent.mkdir(exist_ok=True)
            with ACTION_LOG_PATH.open("a", encoding="utf-8") as file:
                file.write(f"{line}\n")
        except OSError as error:
            LOG.warning("Could not write action log %s: %s", ACTION_LOG_PATH, error)

    def _write_debug(self, frame: np.ndarray, results: list[PluginResult]) -> None:
        if not self.config.save_debug_frame or time.monotonic() - self._last_debug_at < 1:
            return
        self._last_debug_at = time.monotonic()
        output = self._annotate_frame(frame, results)
        Path("debug").mkdir(exist_ok=True)
        cv2.imwrite("debug/latest-frame.png", frame)
        cv2.imwrite("debug/latest-overlay.png", output)

    def preview_frame(self) -> tuple[int, np.ndarray] | None:
        with self._preview_lock:
            if self._latest_preview is None:
                return None
            return self._preview_revision, self._latest_preview.copy()

    def raw_preview_frame(self) -> np.ndarray | None:
        with self._preview_lock:
            return None if self._latest_raw is None else self._latest_raw.copy()

    def _annotate_frame(self, frame: np.ndarray, results: list[PluginResult]) -> np.ndarray:
        output = frame.copy()
        for result in results:
            for overlay in result.overlays:
                x, y, width, height = overlay.roi
                color = (0, 210, 90) if overlay.confidence >= overlay.min_confidence else (0, 165, 255)
                cv2.rectangle(output, (x, y), (x + width, y + height), color, 2)
                cv2.putText(output, overlay.label, (x, max(22, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        label = "No feature plugins enabled"
        if results:
            label = "  |  ".join(result.summary for result in results)
        cv2.rectangle(output, (0, 0), (min(output.shape[1], 760), 44), (13, 25, 41), -1)
        cv2.putText(output, label, (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 244, 255), 2)
        if self.last_event != "Waiting":
            cv2.putText(output, self.last_event, (12, min(output.shape[0] - 12, 66)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        return output

    def _capture(self, screen: mss.mss, left: int, top: int, width: int, height: int) -> np.ndarray:
        raw = np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
