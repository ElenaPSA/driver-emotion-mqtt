from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import time
from pathlib import Path
from typing import Any

import cv2
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(__name__)


def parse_source(value: str) -> int | str:
    """
    Convert a numeric source such as "0" into camera index 0.

    All other values are treated as video paths or stream URLs.
    """
    stripped = value.strip()

    if stripped.isdigit():
        return int(stripped)

    return stripped


def create_capture(
    source: int | str,
    width: int,
    height: int,
    requested_fps: float,
) -> cv2.VideoCapture:
    """
    Open a camera, video file, RTSP stream or HTTP stream.
    """
    logger.info(
        "Opening simulated RTMaps video source: %s",
        source,
    )

    capture = cv2.VideoCapture(source)

    if not capture.isOpened():
        capture.release()

        raise RuntimeError(
            f"Unable to open video source: {source}"
        )

    if isinstance(source, int):
        capture.set(
            cv2.CAP_PROP_FRAME_WIDTH,
            width,
        )

        capture.set(
            cv2.CAP_PROP_FRAME_HEIGHT,
            height,
        )

        capture.set(
            cv2.CAP_PROP_FPS,
            requested_fps,
        )

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

    logger.info(
        "Video source opened: "
        "resolution=%dx%d reported_fps=%s",
        actual_width,
        actual_height,
        actual_fps,
    )

    return capture


def encode_frame(
    frame_number: int,
    timestamp: float,
    frame: Any,
    jpeg_quality: int,
) -> bytes:
    """
    Encode a frame using the RTMaps simulation protocol:

        UTF-8 JSON metadata
        newline byte
        JPEG bytes
    """
    success, encoded_image = cv2.imencode(
        ".jpg",
        frame,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            int(jpeg_quality),
        ],
    )

    if not success:
        raise RuntimeError(
            f"Unable to JPEG-encode frame {frame_number}"
        )

    metadata = json.dumps(
        {
            "frame": frame_number,
            "timestamp": timestamp,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    return (
        metadata
        + b"\n"
        + encoded_image.tobytes()
    )


async def send_control_message(
    websocket: Any,
    payload: dict[str, Any],
) -> None:
    await websocket.send(
        json.dumps(
            payload,
            separators=(",", ":"),
        )
    )


async def wait_for_ack(
    websocket: Any,
    expected_frame: int,
    timeout: float,
) -> None:
    """
    Wait for the Python emotion application to acknowledge the frame.

    Enable this only when WEBSOCKET_SEND_ACK=true in the client.
    """
    response = await asyncio.wait_for(
        websocket.recv(),
        timeout=timeout,
    )

    if not isinstance(response, str):
        raise RuntimeError(
            "Expected a text acknowledgement"
        )

    payload = json.loads(response)

    if payload.get("type") != "ack":
        raise RuntimeError(
            f"Expected ACK, received: {payload}"
        )

    acknowledged_frame = int(
        payload.get("frame", -1)
    )

    if acknowledged_frame != expected_frame:
        raise RuntimeError(
            "Incorrect frame acknowledgement: "
            f"expected={expected_frame}, "
            f"received={acknowledged_frame}"
        )


async def stream_source(
    websocket: Any,
    arguments: argparse.Namespace,
) -> None:
    source = parse_source(arguments.source)

    logger.info(
        "Emotion application connected: %s",
        websocket.remote_address,
    )

    capture: cv2.VideoCapture | None = None

    frames_read = 0
    frames_sent = 0
    invalid_frames = 0
    started = time.perf_counter()

    try:
        capture = await asyncio.to_thread(
            create_capture,
            source,
            arguments.width,
            arguments.height,
            arguments.fps,
        )

        reported_fps = capture.get(
            cv2.CAP_PROP_FPS
        )

        if (
            not math.isfinite(reported_fps)
            or reported_fps <= 0
        ):
            reported_fps = arguments.fps

        is_camera = isinstance(source, int)

        await send_control_message(
            websocket,
            {
                "type": "stream_start",
                "source": str(source),
                "video_name": (
                    f"camera-{source}"
                    if is_camera
                    else Path(str(source)).name
                ),
                "fps": reported_fps,
                "frame_count": (
                    -1
                    if is_camera
                    else int(
                        capture.get(
                            cv2.CAP_PROP_FRAME_COUNT
                        )
                    )
                ),
                "live": is_camera,
            },
        )

        logger.info(
            "RTMaps simulation started: "
            "source=%s fps=%.3f ack=%s",
            source,
            reported_fps,
            arguments.wait_for_ack,
        )

        next_frame_time = time.perf_counter()

        while True:
            success, frame = await asyncio.to_thread(
                capture.read
            )

            if (
                not success
                or frame is None
                or frame.size == 0
            ):
                if is_camera:
                    invalid_frames += 1

                    logger.warning(
                        "Invalid camera frame: count=%d",
                        invalid_frames,
                    )

                    if (
                        invalid_frames
                        >= arguments.max_read_failures
                    ):
                        raise RuntimeError(
                            "Camera stopped supplying "
                            "valid frames"
                        )

                    await asyncio.sleep(0.05)
                    continue

                logger.info(
                    "End of test video reached"
                )
                break

            invalid_frames = 0
            frames_read += 1

            timestamp = (
                time.perf_counter() - started
            )

            message = encode_frame(
                frame_number=frames_read,
                timestamp=timestamp,
                frame=frame,
                jpeg_quality=arguments.jpeg_quality,
            )

            await websocket.send(message)
            frames_sent += 1

            if arguments.wait_for_ack:
                await wait_for_ack(
                    websocket,
                    expected_frame=frames_read,
                    timeout=arguments.ack_timeout,
                )

            if frames_sent % 100 == 0:
                logger.info(
                    "RTMaps simulated frames sent=%d",
                    frames_sent,
                )

            if arguments.display:
                cv2.imshow(
                    "RTMaps simulator output",
                    frame,
                )

                key = cv2.waitKey(1) & 0xFF

                if key in (ord("q"), 27):
                    logger.info(
                        "Simulation stopped by user"
                    )
                    break

            if arguments.realtime:
                next_frame_time += (
                    1.0 / reported_fps
                )

                delay = (
                    next_frame_time
                    - time.perf_counter()
                )

                if delay > 0:
                    await asyncio.sleep(delay)
                else:
                    # Reset accumulated timing drift.
                    next_frame_time = (
                        time.perf_counter()
                    )

        await send_control_message(
            websocket,
            {
                "type": "stream_end",
                "frames_read": frames_read,
                "frames_sent": frames_sent,
                "elapsed_seconds": (
                    time.perf_counter() - started
                ),
            },
        )

        logger.info(
            "RTMaps simulation completed: "
            "read=%d sent=%d elapsed=%.2fs",
            frames_read,
            frames_sent,
            time.perf_counter() - started,
        )

    except ConnectionClosed as exc:
        logger.info(
            "Emotion application disconnected: "
            "code=%s reason=%s sent=%d",
            exc.code,
            exc.reason,
            frames_sent,
        )

    except Exception as exc:
        logger.exception(
            "RTMaps simulation failed after "
            "%d frames",
            frames_sent,
        )

        try:
            await send_control_message(
                websocket,
                {
                    "type": "error",
                    "message": str(exc),
                },
            )
        except ConnectionClosed:
            pass

    finally:
        if capture is not None:
            capture.release()

        cv2.destroyAllWindows()

        logger.info(
            "RTMaps simulator source released"
        )


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Simulate an RTMaps WebSocket component "
            "that sends JPEG video frames."
        )
    )

    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help=(
            "WebSocket listen address. "
            "Default: 127.0.0.1"
        ),
    )

    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="WebSocket listen port. Default: 8765",
    )

    parser.add_argument(
        "--source",
        default="output.mp4",
        help=(
            "Video path, stream URL or camera index. "
            "Examples: output.mp4, 0, rtsp://..."
        ),
    )

    parser.add_argument(
        "--width",
        type=int,
        default=640,
        help="Requested camera width.",
    )

    parser.add_argument(
        "--height",
        type=int,
        default=480,
        help="Requested camera height.",
    )

    parser.add_argument(
        "--fps",
        type=float,
        default=10.0,
        help=(
            "Requested camera FPS and fallback video FPS."
        ),
    )

    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=85,
        help="JPEG quality between 1 and 100.",
    )

    parser.add_argument(
        "--max-size",
        type=int,
        default=16 * 1024 * 1024,
        help="Maximum WebSocket message size.",
    )

    parser.add_argument(
        "--max-read-failures",
        type=int,
        default=20,
        help=(
            "Consecutive invalid camera frames "
            "before stopping."
        ),
    )

    parser.add_argument(
        "--wait-for-ack",
        action="store_true",
        help=(
            "Wait for a JSON acknowledgement "
            "after every frame."
        ),
    )

    parser.add_argument(
        "--ack-timeout",
        type=float,
        default=30.0,
        help="Per-frame acknowledgement timeout.",
    )

    parser.add_argument(
        "--realtime",
        action="store_true",
        help=(
            "Send a video file according to its FPS "
            "instead of as quickly as possible."
        ),
    )

    parser.add_argument(
        "--display",
        action="store_true",
        help=(
            "Display the frames produced by the simulator."
        ),
    )

    return parser


async def async_main(
    arguments: argparse.Namespace,
) -> None:
    if not 1 <= arguments.jpeg_quality <= 100:
        raise ValueError(
            "--jpeg-quality must be between 1 and 100"
        )

    if arguments.fps <= 0:
        raise ValueError(
            "--fps must be positive"
        )

    if arguments.max_read_failures < 1:
        raise ValueError(
            "--max-read-failures must be at least 1"
        )

    logger.info(
        "Starting RTMaps simulator on ws://%s:%d",
        arguments.host,
        arguments.port,
    )

    async def handler(
        websocket: Any,
    ) -> None:
        await stream_source(
            websocket,
            arguments,
        )

    async with serve(
        handler,
        arguments.host,
        arguments.port,
        max_size=arguments.max_size,
        compression=None,
        ping_interval=20,
        ping_timeout=20,
    ) as server:
        await server.serve_forever()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format=(
            "%(asctime)s - %(levelname)s - "
            "%(name)s - %(message)s"
        ),
    )

    parser = create_argument_parser()
    arguments = parser.parse_args()

    try:
        asyncio.run(
            async_main(arguments)
        )

    except KeyboardInterrupt:
        logger.info(
            "RTMaps simulator terminated by user"
        )


if __name__ == "__main__":
    run()