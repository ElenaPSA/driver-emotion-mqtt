from __future__ import annotations

import asyncio
import json
import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


logger = logging.getLogger(__name__)

_END_OF_STREAM = object()


@dataclass(slots=True)
class VideoFrame:
    number: int
    timestamp: float
    image: Any


class WebSocketVideoSource:
    def __init__(
        self,
        host: str,
        port: int,
        queue_size: int = 10,
        max_size: int = 16 * 1024 * 1024,
    ) -> None:
        self.uri = f"ws://{host}:{port}"
        self.max_size = max_size

        self.running = True
        self.finished = False

        self.frames: queue.Queue[Any] = queue.Queue(
            maxsize=queue_size
        )

        self.messages_received = 0
        self.received_frames = 0
        self.invalid_frames = 0

        self.thread = threading.Thread(
            target=self._run,
            name="websocket-video-receiver",
            daemon=True,
        )

        self.thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(self._receiver())

        except Exception:
            logger.exception(
                "Unhandled error in WebSocket receiver thread"
            )

        finally:
            self._finish_stream()

    async def _receiver(self) -> None:
        try:
            async with connect(
                self.uri,
                max_size=self.max_size,
                compression=None,
                ping_interval=20,
                ping_timeout=20,
            ) as websocket:
                logger.info(
                    "Connected to WebSocket %s",
                    self.uri,
                )

                async for message in websocket:
                    if not self.running:
                        break

                    self.messages_received += 1

                    if isinstance(message, str):
                        should_stop = self._handle_control_message(
                            message
                        )

                        if should_stop:
                            break

                        continue

                    frame = self._decode_binary_frame(message)

                    if frame is None:
                        self.invalid_frames += 1
                        continue

                    # Blocking put is intentional. When FER is
                    # slower, the receiver waits rather than
                    # deleting or overwriting the frame.
                    while self.running:
                        try:
                            self.frames.put(
                                frame,
                                timeout=0.5,
                            )
                            break

                        except queue.Full:
                            logger.debug(
                                "Frame queue full; waiting for "
                                "the video processor"
                            )

                    if not self.running:
                        break

                    self.received_frames += 1

                    # Tell the sender that this frame has been
                    # safely received, decoded and queued.
                    await websocket.send(
                        json.dumps(
                            {
                                "type": "ack",
                                "frame": frame.number,
                            }
                        )
                    )

                    if self.received_frames % 100 == 0:
                        logger.info(
                            "WebSocket frames received=%d",
                            self.received_frames,
                        )

        except ConnectionRefusedError:
            logger.exception(
                "Unable to connect to WebSocket %s. "
                "Start video_stream_server.py first.",
                self.uri,
            )

        except ConnectionClosed as exc:
            if exc.code == 1000:
                logger.info(
                    "WebSocket connection closed normally"
                )
            else:
                logger.warning(
                    "WebSocket connection closed: "
                    "code=%s reason=%s",
                    exc.code,
                    exc.reason,
                )

        except Exception:
            logger.exception(
                "WebSocket receiver failed"
            )

    def _handle_control_message(
        self,
        message: str,
    ) -> bool:
        try:
            control = json.loads(message)

        except json.JSONDecodeError:
            logger.warning(
                "Received an invalid WebSocket control message"
            )
            return False

        message_type = control.get("type")

        if message_type == "stream_start":
            logger.info(
                "Stream started: video=%s fps=%s frames=%s",
                control.get("video_name"),
                control.get("fps"),
                control.get("frame_count"),
            )
            return False

        if message_type == "stream_end":
            logger.info(
                "Stream ended: server sent %s frames",
                control.get("frames_sent"),
            )
            return True

        if message_type == "error":
            logger.error(
                "Video server error: %s",
                control.get("message"),
            )
            return True

        logger.warning(
            "Unknown WebSocket control message: %s",
            control,
        )

        return False

    @staticmethod
    def _decode_binary_frame(
        message: bytes,
    ) -> VideoFrame | None:
        try:
            # Binary format:
            # first line = JSON metadata
            # remaining bytes = JPEG image
            separator_index = message.find(b"\n")

            if separator_index < 0:
                logger.warning(
                    "Frame message has no metadata separator"
                )
                return None

            metadata_bytes = message[:separator_index]
            image_bytes = message[separator_index + 1:]

            metadata = json.loads(
                metadata_bytes.decode("utf-8")
            )

            frame_number = int(metadata["frame"])
            timestamp = float(metadata["timestamp"])

            if not image_bytes:
                logger.warning(
                    "Received empty image for frame %d",
                    frame_number,
                )
                return None

            image_array = np.frombuffer(
                image_bytes,
                dtype=np.uint8,
            )

            frame = cv2.imdecode(
                image_array,
                cv2.IMREAD_COLOR,
            )

            if frame is None or frame.size == 0:
                logger.warning(
                    "OpenCV could not decode frame %d",
                    frame_number,
                )
                return None

            return VideoFrame(
                number=frame_number,
                timestamp=timestamp,
                image=frame,
            )

        except (
            KeyError,
            TypeError,
            ValueError,
            UnicodeDecodeError,
            json.JSONDecodeError,
        ) as exc:
            logger.warning(
                "Invalid binary frame message: %s",
                exc,
            )
            return None

        except Exception:
            logger.exception(
                "Unexpected error decoding WebSocket frame"
            )
            return None

    def _finish_stream(self) -> None:
        if self.finished:
            return

        self.finished = True
        self.running = False

        # Frames already in the queue remain before the marker.
        while True:
            try:
                self.frames.put(
                    _END_OF_STREAM,
                    timeout=0.5,
                )
                break

            except queue.Full:
                # The processor is still consuming frames.
                continue

        logger.info(
            "WebSocket input finished: "
            "messages=%d valid_frames=%d invalid_frames=%d",
            self.messages_received,
            self.received_frames,
            self.invalid_frames,
        )

    def read(self) -> VideoFrame | None:
        item = self.frames.get()

        if item is _END_OF_STREAM:
            logger.info(
                "All queued WebSocket frames consumed"
            )
            return None

        return item

    def release(self) -> None:
        self.running = False

        if (
            self.thread.is_alive()
            and self.thread is not threading.current_thread()
        ):
            self.thread.join(timeout=2.0)

        logger.info(
            "WebSocket video source released"
        )