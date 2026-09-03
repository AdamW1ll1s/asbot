from __future__ import annotations

import logging
from pathlib import Path
import threading
import time

import cv2
import mss
import numpy as np

from .config import AppConfig
from .health import HealthBarDetector
from .input import KeyboardExecutor
from .windows import client_rect, find_window, is_foreground


LOG = logging.getLogger(__name__)


class AutomationRunner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._keyboard = KeyboardExecutor()
        self._detector = HealthBarDetector(config.health_bar)
        self._last_action_at = 0.0

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

    def toggle(self) -> None:
        self.stop() if self.running else self.start()

    def _run(self) -> None:
        try:
            hwnd = find_window(self.config.window.title_contains)
            if hwnd is None:
                LOG.error("No visible window contains title: %r", self.config.window.title_contains)
                return
            with mss.mss() as screen:
                while not self._cancel.is_set():
                    if self.config.window.require_foreground and not is_foreground(hwnd):
                        LOG.warning("Target window lost focus; stopping")
                        return
                    rect = client_rect(hwnd)
                    if rect is None:
                        LOG.warning("Target client area is unavailable; stopping")
                        return
                    client_bgr = self._capture(screen, rect.left, rect.top, rect.width, rect.height)
                    reading = self._detector.detect(client_bgr)
                    if reading is not None:
                        LOG.info("HP %.1f%% (confidence %.2f)", reading.percent, reading.confidence)
                        self._apply_health_rule(reading.percent, reading.confidence)
                    self._cancel.wait(self.config.poll_interval_ms / 1000)
        except Exception:
            LOG.exception("Automation failed safely")
        finally:
            self._keyboard.release_all()
            self._cancel.set()

    def _apply_health_rule(self, percent: float, confidence: float) -> None:
        rule = self.config.rules
        if confidence < self.config.health_bar.min_confidence or percent >= rule.heal_below_percent:
            return
        now = time.monotonic()
        if now - self._last_action_at < rule.cooldown_ms / 1000:
            return
        self._last_action_at = now
        LOG.warning("HP below threshold; tapping %s", rule.heal_key)
        self._keyboard.tap(rule.heal_key, duration_ms=50, cancelled=self._cancel)

    def _capture(self, screen: mss.mss, left: int, top: int, width: int, height: int) -> np.ndarray:
        raw = np.asarray(screen.grab({"left": left, "top": top, "width": width, "height": height}))
        bgr = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        if self.config.save_debug_frame:
            cv2.imwrite(str(Path("debug-frame.png")), bgr)
        return bgr
