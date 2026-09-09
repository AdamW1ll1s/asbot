import cv2
import numpy as np

from game_assist.config import HealthBarConfig
from game_assist.health import HealthBarDetector


def test_detects_horizontal_red_fill() -> None:
    image = np.zeros((100, 300, 3), dtype=np.uint8)
    # BGR red rectangle: x=20..119 is approximately 50% of a 200px bar.
    cv2.rectangle(image, (20, 30), (119, 47), (0, 0, 255), thickness=-1)
    detector = HealthBarDetector(
        HealthBarConfig(
            roi=(20, 30, 200, 18),
            hsv_lower=(0, 110, 80),
            hsv_upper=(10, 255, 255),
            column_coverage=0.35,
            min_confidence=0.7,
        )
    )
    result = detector.detect(image)
    assert result is not None
    assert 49 <= result.percent <= 51
    assert result.confidence > 0.95


def test_combines_primary_and_additional_hsv_ranges() -> None:
    image = np.zeros((30, 100, 3), dtype=np.uint8)
    image[:, :25] = (0, 0, 255)  # Red, matched by the primary range.
    image[:, 25:50] = (0, 255, 0)  # Green, matched by the additional range.
    detector = HealthBarDetector(
        HealthBarConfig(
            roi=(0, 0, 100, 30),
            hsv_lower=(0, 110, 80),
            hsv_upper=(10, 255, 255),
            hsv_ranges=(((50, 110, 80), (70, 255, 255)),),
            column_coverage=0.35,
            min_confidence=0.7,
        )
    )

    result = detector.detect(image)

    assert result is not None
    assert 49 <= result.percent <= 51
    assert result.confidence > 0.95
