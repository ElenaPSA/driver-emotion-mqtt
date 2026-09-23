from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from typing import Any

import cv2
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

from .config import Settings


logger = logging.getLogger(__name__)


def encode_frame(
    frame_number: int,
    timestamp: float,
    frame: Any,
    jpeg_quality: int,
) -> bytes:
    success, encoded = cv2.imencode(
        ".jpg",
        frame,
        [
            int(cv2.IMWRITE_JPEG_QUALITY),
            jpeg_quality,
        ],
    )

    if not success:
        raise RuntimeError(
            f"Unable to encode frame {frame_number}"
        )

    metadata = json.dumps(
        {
            "frame": frame_number,
            "timestamp": timestamp,
        },
        separators=(",", ":"),
    ).encode("utf-8")

    return metadata + b"\n" + encoded.tobytes()


async def wait_for_ack(
    websocket: Any,
    expected_frame: int,
) -> None:
    response = await websocket.recv()

    if not isinstance(response, str):
        raise RuntimeError(
            "Expected text ACK from WebSocket client"
        )

    payload = json.loads(response)

    if payload.get("type") != "ack":
        raise RuntimeError(
            f"Expected ACK, received {payload}"
        )

    received_frame = int(payload.get("frame", -1))

    if received_frame != expected_frame:
        raise RuntimeError(
            "Incorrect frame acknowledgement: "
            f"expected={expected_frame} "
            f"received={received_frame}"
        )


async def stream_video(
    websocket: Any,
    settings: Settings,
) -> None:
    logger.info(
        "WebSocket client connected: %s",
        websocket.remote_address,
    )

    capture = cv2.VideoCapture(
        str(settings.video_path)
    )

    if not capture.isOpened():
        message = (
            f"Unable to open video: "
            f"{settings.video_path.resolve()}"
        )

        await websocket.send(
            json.dumps(
                {
                    "type": "error",
                    "message": message,
                }
            )
        )

        logger.error(message)
        return

    frames_sent = 0
    started = time.perf_counter()

    try:
        fps = capture.get(cv2.CAP_PROP_FPS)

        if not math.isfinite(fps) or fps <= 0:
            fps = 25.0
            logger.warning(
                "Invalid FPS; using %.1f",
                fps,
            )

        frame_count = int(
            capture.get(cv2.CAP_PROP_FRAME_COUNT)
        )

        logger.info(
            "Streaming video=%s fps=%.3f declared_frames=%d",
            settings.video_path.resolve(),
            fps,
            frame_count,
        )

        await websocket.send(
            json.dumps(
                {
                    "type": "stream_start",
                    "video_name": settings.video_path.name,
                    "fps": fps,
                    "frame_count": frame_count,
                }
            )
        )

        while True:
            success, frame = capture.read()

            if not success:
                break

            frames_sent += 1
            timestamp = (frames_sent - 1) / fps

            message = encode_frame(
                frame_number=frames_sent,
                timestamp=timestamp,
                frame=frame,
                jpeg_quality=settings.jpeg_quality,
            )

            await websocket.send(message)

            # Do not send the next frame until the receiver
            # confirms that this frame is decoded and queued.
            await wait_for_ack(
                websocket,
                expected_frame=frames_sent,
            )

            if frames_sent % 100 == 0:
                logger.info(
                    "Video frames sent=%d/%d",
                    frames_sent,
                    frame_count,
                )

        await websocket.send(
            json.dumps(
                {
                    "type": "stream_end",
                    "frames_sent": frames_sent,
                    "declared_frames": frame_count,
                }
            )
        )

        logger.info(
            "Video streaming completed: "
            "sent=%d declared=%d elapsed=%.2fs",
            frames_sent,
            frame_count,
            time.perf_counter() - started,
        )

    except ConnectionClosed as exc:
        logger.warning(
            "Video client disconnected: "
            "code=%s reason=%s sent=%d",
            exc.code,
            exc.reason,
            frames_sent,
        )

    except Exception:
        logger.exception(
            "Video streaming failed after %d frames",
            frames_sent,
        )

    finally:
        capture.release()
        logger.info(
            "Video capture released"
        )


async def main() -> None:
    settings = Settings()
    settings.validate()

    if not settings.video_path.exists():
        raise FileNotFoundError(
            f"Video not found: "
            f"{settings.video_path.resolve()}"
        )

    logger.info(
        "Starting video WebSocket server on %s",
        settings.websocket_uri,
    )

    async def handler(websocket: Any) -> None:
        await stream_video(
            websocket,
            settings,
        )

    async with serve(
        handler,
        settings.websocket_host,
        settings.websocket_port,
        max_size=settings.websocket_max_size,
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

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        logger.info(
            "Video WebSocket server terminated by user"
        )


if __name__ == "__main__":
    run()