from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import HealthBarConfig


@dataclass(frozen=True)
class HealthReading:
    percent: float
    confidence: float


class HealthBarDetector:
    """Measures a horizontal, color-filled health bar inside a client-area ROI."""

    def __init__(self, config: HealthBarConfig) -> None:
        self.config = config

    def detect(self, client_bgr: np.ndarray) -> HealthReading | None:
        x, y, width, height = self.config.roi
        if x < 0 or y < 0 or width <= 0 or height <= 0:
            return None
        roi = client_bgr[y : y + height, x : x + width]
        if roi.shape[:2] != (height, width):
            return None

        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        for lower, upper in self.config.hsv_ranges or ((self.config.hsv_lower, self.config.hsv_upper),):
            mask = cv2.bitwise_or(mask, cv2.inRange(hsv, np.array(lower, dtype=np.uint8), np.array(upper, dtype=np.uint8)))
        column_match = (mask > 0).mean(axis=0)
        filled = column_match >= self.config.column_coverage
        if not filled.any():
            return HealthReading(percent=0.0, confidence=0.0)

        first = int(np.argmax(filled))
        end = first
        gap = 0
        for index in range(first, width):
            if filled[index]:
                end = index
                gap = 0
            else:
                gap += 1
                if gap >= 3:
                    break

        filled_width = end - first + 1
        percent = min(100.0, max(0.0, filled_width / width * 100.0))
        observed_coverage = float(column_match[first : end + 1].mean())
        continuity = float(filled[first : end + 1].mean())
        return HealthReading(percent=percent, confidence=observed_coverage * continuity)
