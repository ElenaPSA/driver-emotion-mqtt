from __future__ import annotations

import math
from typing import Any

import cv2
from fer.fer import FER

from .serialization import to_json_value


class DriverEmotionDetector:
    def __init__(self, use_mtcnn: bool = True) -> None:
        self.detector = FER(mtcnn=use_mtcnn)

    @staticmethod
    def _largest_face(
        detections: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        valid = [
            detection for detection in detections
            if len(detection.get("box", [])) >= 4
        ]
        if not valid:
            return None
        return max(
            valid,
            key=lambda detection: max(0, detection["box"][2])
            * max(0, detection["box"][3]),
        )

    def analyze(
        self, frame: Any,
    ) -> tuple[list[dict[str, Any]], str | None, float | None]:
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        detections = to_json_value(self.detector.detect_emotions(rgb_frame))
        driver = self._largest_face(detections)
        if driver is None or not driver.get("emotions"):
            return detections, None, None

        scores = driver["emotions"]
        dominant = max(scores, key=scores.get)
        confidence = float(scores[dominant])
        if not math.isfinite(confidence):
            confidence = None
        return detections, dominant, confidence
