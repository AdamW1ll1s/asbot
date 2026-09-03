from __future__ import annotations

from dataclasses import replace
import logging
from pathlib import Path
import threading
import time

import cv2
import mss
import numpy as np

from .config import AppConfig, HealthBarConfig
from .health import HealthBarDetector
from .input import KeyboardExecutor
from .windows import activate_window, client_rect, find_window, is_foreground


LOG = logging.getLogger(__name__)


class AutomationRunner:
    def __init__(self, config: AppConfig, preview_only: bool = False) -> None:
        self.config = config
        self.preview_only = preview_only
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._keyboard = KeyboardExecutor()
        self._detector = HealthBarDetector(config.health_bar)
        self._last_action_at = 0.0
        self._reading_streak = 0
        self.last_reading: tuple[float, float] | None = None
        self.last_event = "Waiting"
        self.paused_for_focus = False
        self._last_debug_at = 0.0
        self._last_recognition_at = 0.0
        self._preview_lock = threading.Lock()
        self._latest_preview: np.ndarray | None = None
        self._latest_raw: np.ndarray | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.running:
            return
        self._cancel.clear()
        self._thread = threading.Thread(target=self._run, name="automation-runner", daemon=True)
        self._thread.start()
        LOG.info("Automation started")

    def stop(self) -> None:
        self._cancel.set()
        self._keyboard.release_all()
        LOG.info("Automation stopped")

    def update_health_bar(self, config: HealthBarConfig) -> None:
        """Apply calibration changes to a running preview."""
        self.config = replace(self.config, health_bar=config)
        self._detector = HealthBarDetector(config)
        self._reading_streak = 0
        self.last_reading = None
        self._last_recognition_at = 0.0

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def _run(self) -> None:
        try:
            hwnd = find_window(self.config.window.title_contains, self.config.window.process_id)
            if hwnd is None:
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
                        self._cancel.wait(min(self.config.poll_interval_ms / 1000, until_next_recognition))
                        continue
                    rect = client_rect(hwnd)
                    if rect is None:
                        LOG.warning("Target client area is unavailable; stopping")
                        return
                    client_bgr = self._capture(screen, rect.left, rect.top, rect.width, rect.height)
                    self._last_recognition_at = now
                    reading = self._detector.detect(client_bgr)
                    if reading is not None:
                        self.last_reading = (reading.percent, reading.confidence)
                        LOG.info("HP %.1f%% (confidence %.2f)", reading.percent, reading.confidence)
                        self._reading_streak = self._reading_streak + 1 if reading.confidence >= self.config.health_bar.min_confidence else 0
                        if not self.preview_only and self._reading_streak >= self.config.health_bar.consecutive_frames:
                            self._apply_health_rule(reading.percent, reading.confidence)
                    else:
                        self._reading_streak = 0
                    with self._preview_lock:
                        self._latest_preview = self._annotate_frame(client_bgr, reading)
                        self._latest_raw = client_bgr.copy()
                    self._write_debug(client_bgr, reading)
        except Exception:
            LOG.exception("Automation failed safely")
        finally:
            self.paused_for_focus = False
            self._keyboard.release_all()
            self._cancel.set()

    def _apply_health_rule(self, percent: float, confidence: float) -> None:
        for rule in (self.config.rules, *self.config.additional_rules):
            if confidence < self.config.health_bar.min_confidence or percent >= rule.heal_below_percent:
                continue
            now = time.monotonic()
            if now - self._last_action_at < rule.cooldown_ms / 1000:
                continue
            self._last_action_at = now
            self.last_event = f"{rule.name}: {percent:.1f}% → {rule.heal_key}"
            LOG.warning("%s", self.last_event)
            if self.config.save_debug_frame:
                Path("debug").mkdir(exist_ok=True)
                with Path("debug/events.log").open("a", encoding="utf-8") as file:
                    file.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {self.last_event}\n")
            self._keyboard.tap(rule.heal_key, duration_ms=rule.hold_ms, cancelled=self._cancel)
            break

    def _write_debug(self, frame: np.ndarray, reading: object) -> None:
        if not self.config.save_debug_frame or time.monotonic() - self._last_debug_at < 1:
            return
        self._last_debug_at = time.monotonic()
        output = self._annotate_frame(frame, reading)
        Path("debug").mkdir(exist_ok=True)
        cv2.imwrite("debug/latest-frame.png", frame)
        cv2.imwrite("debug/latest-overlay.png", output)

    def preview_frame(self) -> np.ndarray | None:
        with self._preview_lock:
            return None if self._latest_preview is None else self._latest_preview.copy()

    def raw_preview_frame(self) -> np.ndarray | None:
        with self._preview_lock:
            return None if self._latest_raw is None else self._latest_raw.copy()

    def _annotate_frame(self, frame: np.ndarray, reading: object) -> np.ndarray:
        output = frame.copy()
        x, y, width, height = self.config.health_bar.roi
        confidence = 0.0 if reading is None else reading.confidence
        color = (0, 210, 90) if confidence >= self.config.health_bar.min_confidence else (0, 165, 255)
        cv2.rectangle(output, (x, y), (x + width, y + height), color, 2)
        cv2.putText(output, "Health ROI", (x, max(22, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        label = "HP unavailable" if reading is None else f"HP {reading.percent:.1f}% | confidence {reading.confidence:.2f} | frames {self._reading_streak}/{self.config.health_bar.consecutive_frames}"
        cv2.rectangle(output, (0, 0), (min(output.shape[1], 760), 44), (13, 25, 41), -1)
        cv2.putText(output, label, (12, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (235, 244, 255), 2)
        if self.last_event != "Waiting":
            cv2.putText(output, self.last_event, (12, min(output.shape[0] - 12, 66)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 220, 255), 1)
        return output

    def _capture(self, screen: mss.mss, left: int, top: int, width: int, height: int) -> np.ndarray:
        raw = np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))
        return cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
