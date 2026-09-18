from __future__ import annotations

import logging
import math
import time
from typing import Any

import cv2

from .config import Settings
from .emotion_detector import DriverEmotionDetector
from .mqtt_publisher import MqttPublisher
from .serialization import save_json

logger = logging.getLogger(__name__)
WINDOW_NAME = "Driver emotion detection"


def _render(frame: Any, detections: list[dict[str, Any]], label: str) -> Any:
    output = frame.copy()
    for detection in detections:
        box = detection.get("box", [])
        if len(box) >= 4:
            x, y, width, height = map(int, box[:4])
            x, y = max(0, x), max(0, y)
            cv2.rectangle(output, (x, y), (x + width, y + height), (0, 255, 0), 2)
    cv2.putText(output, label, (20, 40), cv2.FONT_HERSHEY_SIMPLEX,
                1.0, (0, 255, 0), 2, cv2.LINE_AA)
    return output


def process_video(settings: Settings) -> None:
    settings.validate()
    if not settings.video_path.exists():
        raise FileNotFoundError(f"Video not found: {settings.video_path.resolve()}")

    capture = cv2.VideoCapture(str(settings.video_path))
    if not capture.isOpened():
        raise RuntimeError(f"Unable to open video: {settings.video_path.resolve()}")

    publisher: MqttPublisher | None = None
    all_emotions: list[dict[str, Any]] = []
    dominant_emotions: list[dict[str, Any]] = []
    frames_read = frames_processed = messages_queued = 0
    started = time.perf_counter()

    try:
        fps = capture.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            fps = 25.0
            logger.warning("Invalid FPS; using %.1f", fps)

        logger.info("Initializing FER detector")
        detector = DriverEmotionDetector(settings.use_mtcnn)
        publisher = MqttPublisher(settings)
        publisher.connect()

        while True:
            success, frame = capture.read()
            if not success:
                break
            frames_read += 1
            if (frames_read - 1) % settings.process_every_n_frames:
                continue

            frames_processed += 1
            timestamp = (frames_read - 1) / fps
            detections, dominant, confidence = detector.analyze(frame)
            common = {"frame": frames_read, "timestamp": round(timestamp, 3)}
            all_emotions.append({**common, "emotions": detections})
            dominant_emotions.append({
                **common,
                "dominant_emotion": dominant,
                "confidence": confidence,
            })
            if publisher.publish({
                **common,
                "dominant_emotion": dominant,
                "confidence": confidence,
                "emotions": detections,
            }):
                messages_queued += 1

            if settings.log_every_n_frames > 0 and (
                frames_processed % settings.log_every_n_frames == 0
            ):
                logger.info(
                    "Frame %d | %.2fs | faces=%d | emotion=%s | confidence=%s",
                    frames_read, timestamp, len(detections), dominant,
                    f"{confidence:.4f}" if confidence is not None else "N/A",
                )

            if settings.display_video:
                label = "No face detected" if dominant is None else (
                    f"{dominant}: {confidence:.3f}"
                    if confidence is not None else dominant
                )
                cv2.imshow(WINDOW_NAME, _render(frame, detections, label))
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
    finally:
        capture.release()
        cv2.destroyAllWindows()
        if publisher is not None:
            publisher.disconnect()
        save_json(settings.captured_emotions_path, all_emotions)
        save_json(settings.dominant_emotions_path, dominant_emotions)
        logger.info(
            "Finished: read=%d processed=%d queued=%d elapsed=%.2fs",
            frames_read, frames_processed, messages_queued,
            time.perf_counter() - started,
        )
