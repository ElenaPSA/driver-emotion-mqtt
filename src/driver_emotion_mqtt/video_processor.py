from __future__ import annotations

import logging
import os
import time
from typing import Any

import cv2

from .config import Settings
from .emotion_detector import DriverEmotionDetector
from .mqtt_publisher import MqttPublisher
from .serialization import save_json


logger = logging.getLogger(__name__)

WINDOW_NAME = "Driver emotion detection"

MAXIMUM_CONSECUTIVE_READ_FAILURES = 20


def _create_camera_capture(
    settings: Settings,
) -> cv2.VideoCapture:
    """
    Open the laptop webcam or an external USB camera.

    On Windows, DirectShow is used as the OpenCV backend.
    On Linux, OpenCV selects the available backend.
    """
    logger.info(
        "Opening local camera index=%d",
        settings.camera_index,
    )

    if os.name == "nt":
        capture = cv2.VideoCapture(
            settings.camera_index,
            cv2.CAP_DSHOW,
        )
    else:
        capture = cv2.VideoCapture(
            settings.camera_index,
            cv2.CAP_ANY,
        )

    if not capture.isOpened():
        capture.release()

        raise RuntimeError(
            "Unable to open camera index "
            f"{settings.camera_index}. "
            "Close applications that may be using the camera "
            "and verify CAMERA_INDEX."
        )

    # Request the configured camera properties.
    # The camera driver may choose slightly different values.
    capture.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        settings.camera_width,
    )

    capture.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        settings.camera_height,
    )

    capture.set(
        cv2.CAP_PROP_FPS,
        settings.camera_fps,
    )

    # Reduce latency when supported by the backend.
    capture.set(
        cv2.CAP_PROP_BUFFERSIZE,
        1,
    )

    actual_width = int(
        capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    )

    actual_height = int(
        capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    )

    actual_fps = capture.get(
        cv2.CAP_PROP_FPS
    )

    try:
        backend_name = capture.getBackendName()
    except cv2.error:
        backend_name = "unknown"

    logger.info(
        "Camera opened: index=%d backend=%s "
        "resolution=%dx%d reported_fps=%.2f",
        settings.camera_index,
        backend_name,
        actual_width,
        actual_height,
        actual_fps,
    )

    return capture


def _render(
    frame: Any,
    detections: list[dict[str, Any]],
    label: str,
    frame_number: int,
    elapsed_seconds: float,
) -> Any:
    """
    Draw face boxes and emotion information over the frame.
    """
    output = frame.copy()

    frame_height, frame_width = output.shape[:2]

    for detection in detections:
        box = detection.get(
            "box",
            [],
        )

        if len(box) < 4:
            continue

        x, y, width, height = map(
            int,
            box[:4],
        )

        x = max(0, x)
        y = max(0, y)
        width = max(0, width)
        height = max(0, height)

        x2 = min(
            frame_width - 1,
            x + width,
        )

        y2 = min(
            frame_height - 1,
            y + height,
        )

        cv2.rectangle(
            output,
            (x, y),
            (x2, y2),
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
        f"Time: {elapsed_seconds:.1f} s",
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        output,
        label,
        (20, 100),
        cv2.FONT_HERSHEY_SIMPLEX,
        1.0,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        output,
        "Press Q or ESC to stop",
        (20, frame_height - 20),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.6,
        (255, 255, 255),
        2,
        cv2.LINE_AA,
    )

    return output


def _show_skipped_frame(
    frame: Any,
    frame_number: int,
) -> bool:
    """
    Display a frame where FER inference was intentionally skipped.

    Return True when the user requests shutdown.
    """
    preview = frame.copy()

    cv2.putText(
        preview,
        f"Frame: {frame_number}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 0),
        2,
        cv2.LINE_AA,
    )

    cv2.putText(
        preview,
        "Emotion inference skipped",
        (20, 70),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 165, 255),
        2,
        cv2.LINE_AA,
    )

    cv2.imshow(
        WINDOW_NAME,
        preview,
    )

    key = cv2.waitKey(1) & 0xFF

    return key in (
        ord("q"),
        27,
    )


def process_video(
    settings: Settings,
) -> None:
    """
    Capture frames directly from the local webcam, run FER,
    and publish every processed result through MQTT.
    """
    settings.validate()

    capture: cv2.VideoCapture | None = None
    publisher: MqttPublisher | None = None

    all_emotions: list[dict[str, Any]] = []
    dominant_emotions: list[dict[str, Any]] = []

    frames_read = 0
    frames_processed = 0
    frames_skipped = 0
    camera_read_failures = 0
    messages_published = 0
    publish_failures = 0

    started = time.perf_counter()

    try:
        # -----------------------------------------------------
        # Open local webcam
        # -----------------------------------------------------
        capture = _create_camera_capture(
            settings
        )

        # -----------------------------------------------------
        # Create FER detector once
        # -----------------------------------------------------
        logger.info(
            "Initializing FER detector: use_mtcnn=%s",
            settings.use_mtcnn,
        )

        detector = DriverEmotionDetector(
            settings.use_mtcnn
        )

        # -----------------------------------------------------
        # Connect MQTT publisher
        # -----------------------------------------------------
        logger.info(
            "Connecting to MQTT broker %s:%d",
            settings.mqtt_host,
            settings.mqtt_port,
        )

        publisher = MqttPublisher(settings)
        publisher.connect()

        logger.info(
            "Local webcam processing started"
        )

        logger.info(
            "PROCESS_EVERY_N_FRAMES=%d",
            settings.process_every_n_frames,
        )

        # -----------------------------------------------------
        # Webcam processing loop
        # -----------------------------------------------------
        while True:
            success, frame = capture.read()

            if (
                not success
                or frame is None
                or frame.size == 0
            ):
                camera_read_failures += 1

                logger.warning(
                    "Invalid camera frame: "
                    "consecutive_failures=%d/%d",
                    camera_read_failures,
                    MAXIMUM_CONSECUTIVE_READ_FAILURES,
                )

                if (
                    camera_read_failures
                    >= MAXIMUM_CONSECUTIVE_READ_FAILURES
                ):
                    raise RuntimeError(
                        "The webcam stopped providing "
                        "valid frames"
                    )

                time.sleep(0.05)
                continue

            camera_read_failures = 0
            frames_read += 1

            frame_number = frames_read

            timestamp = (
                time.perf_counter()
                - started
            )

            # PROCESS_EVERY_N_FRAMES=1:
            # process all camera frames.
            #
            # PROCESS_EVERY_N_FRAMES=2:
            # process frames 1, 3, 5, 7...
            should_process = (
                (frame_number - 1)
                % settings.process_every_n_frames
                == 0
            )

            if not should_process:
                frames_skipped += 1

                if settings.display_video:
                    should_stop = _show_skipped_frame(
                        frame,
                        frame_number,
                    )

                    if should_stop:
                        logger.info(
                            "Processing interrupted by user"
                        )
                        break

                continue

            # -------------------------------------------------
            # Emotion detection
            # -------------------------------------------------
            frames_processed += 1

            detections, dominant, confidence = (
                detector.analyze(frame)
            )

            common = {
                "frame": frame_number,
                "timestamp": round(
                    timestamp,
                    3,
                ),
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

            # -------------------------------------------------
            # MQTT publication
            # -------------------------------------------------
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

            # -------------------------------------------------
            # Logs
            # -------------------------------------------------
            if (
                settings.log_every_n_frames > 0
                and frames_processed
                % settings.log_every_n_frames
                == 0
            ):
                logger.info(
                    "Frame=%d | timestamp=%.3fs | "
                    "faces=%d | emotion=%s | "
                    "confidence=%s",
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

            # -------------------------------------------------
            # Display
            # -------------------------------------------------
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
                    frame=frame,
                    detections=detections,
                    label=label,
                    frame_number=frame_number,
                    elapsed_seconds=timestamp,
                )

                cv2.imshow(
                    WINDOW_NAME,
                    displayed_frame,
                )

                key = cv2.waitKey(1) & 0xFF

                if key in (
                    ord("q"),
                    27,
                ):
                    logger.info(
                        "Processing interrupted by user"
                    )
                    break

    finally:
        # -----------------------------------------------------
        # Cleanup
        # -----------------------------------------------------
        if capture is not None:
            capture.release()

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
            "Finished: read=%d processed=%d "
            "skipped=%d published=%d "
            "publish_failures=%d elapsed=%.2fs",
            frames_read,
            frames_processed,
            frames_skipped,
            messages_published,
            publish_failures,
            time.perf_counter() - started,
        )