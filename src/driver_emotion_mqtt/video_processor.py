from __future__ import annotations

import logging
import time
from typing import Any

import cv2

from .config import Settings
from .emotion_detector import DriverEmotionDetector
from .mqtt_publisher import MqttPublisher
from .serialization import save_json
from .websocket_video_source import (
    VideoFrame,
    WebSocketVideoSource,
)


logger = logging.getLogger(__name__)

WINDOW_NAME = "Driver emotion detection"


def _render(
    frame: Any,
    detections: list[dict[str, Any]],
    label: str,
    frame_number: int,
) -> Any:
    output = frame.copy()

    for detection in detections:
        box = detection.get("box", [])

        if len(box) >= 4:
            x, y, width, height = map(
                int,
                box[:4],
            )

            x = max(0, x)
            y = max(0, y)
            width = max(0, width)
            height = max(0, height)

            cv2.rectangle(
                output,
                (x, y),
                (x + width, y + height),
                (0, 255, 0),
                2,
            )

    cv2.putText(
        output,
        f"Frame: {frame_number}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        output,
        label,
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    return output


def process_video(settings: Settings) -> None:
    settings.validate()

    logger.info(
        "WebSocket source=%s",
        settings.websocket_uri,
    )

    logger.info(
        "PROCESS_EVERY_N_FRAMES=%d",
        settings.process_every_n_frames,
    )

    source: WebSocketVideoSource | None = None
    publisher: MqttPublisher | None = None

    all_emotions: list[dict[str, Any]] = []
    dominant_emotions: list[dict[str, Any]] = []

    frames_read = 0
    frames_processed = 0
    frames_skipped = 0
    messages_published = 0
    publish_failures = 0

    started = time.perf_counter()

    try:
        logger.info(
            "Initializing FER detector"
        )

        detector = DriverEmotionDetector(
            settings.use_mtcnn
        )

        publisher = MqttPublisher(settings)
        publisher.connect()

        source = WebSocketVideoSource(
            host=settings.websocket_host,
            port=settings.websocket_port,
            queue_size=settings.websocket_queue_size,
            max_size=settings.websocket_max_size,
        )

        while True:
            received_frame = source.read()

            if received_frame is None:
                logger.info(
                    "End of WebSocket video stream"
                )
                break

            frames_read += 1

            frame_number = received_frame.number
            timestamp = received_frame.timestamp
            frame = received_frame.image

            if (
                (frame_number - 1)
                % settings.process_every_n_frames
                != 0
            ):
                frames_skipped += 1
                continue

            frames_processed += 1

            detections, dominant, confidence = (
                detector.analyze(frame)
            )

            common = {
                "frame": frame_number,
                "timestamp": round(timestamp, 3),
            }

            all_emotions.append(
                {
                    **common,
                    "emotions": detections,
                }
            )

            dominant_emotions.append(
                {
                    **common,
                    "dominant_emotion": dominant,
                    "confidence": confidence,
                }
            )

            payload = {
                "name": "DriverEmotionState",
                "data": {
                    **common,
                    "dominant_emotion": dominant,
                    "confidence": confidence,
                    "emotions": detections,
                },
            }

            if publisher.publish(payload):
                messages_published += 1
            else:
                publish_failures += 1

            if (
                settings.log_every_n_frames > 0
                and frames_processed
                % settings.log_every_n_frames
                == 0
            ):
                logger.info(
                    "Frame %d | %.3fs | faces=%d | "
                    "emotion=%s | confidence=%s",
                    frame_number,
                    timestamp,
                    len(detections),
                    dominant,
                    (
                        f"{confidence:.4f}"
                        if confidence is not None
                        else "N/A"
                    ),
                )

            if settings.display_video:
                if dominant is None:
                    label = "No face detected"
                elif confidence is None:
                    label = dominant
                else:
                    label = (
                        f"{dominant}: "
                        f"{confidence:.3f}"
                    )

                displayed_frame = _render(
                    frame,
                    detections,
                    label,
                    frame_number,
                )

                cv2.imshow(
                    WINDOW_NAME,
                    displayed_frame,
                )

                key = cv2.waitKey(1) & 0xFF

                if key in (ord("q"), 27):
                    logger.info(
                        "Processing interrupted by user"
                    )
                    break

    finally:
        if source is not None:
            source.release()

        cv2.destroyAllWindows()

        if publisher is not None:
            publisher.disconnect()

        save_json(
            settings.captured_emotions_path,
            all_emotions,
        )

        save_json(
            settings.dominant_emotions_path,
            dominant_emotions,
        )

        logger.info(
            "Finished: read=%d processed=%d skipped=%d "
            "published=%d publish_failures=%d elapsed=%.2fs",
            frames_read,
            frames_processed,
            frames_skipped,
            messages_published,
            publish_failures,
            time.perf_counter() - started,
        )