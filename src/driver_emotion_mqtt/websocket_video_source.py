from __future__ import annotations

import asyncio
import base64
import json
import logging
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .config import Settings


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
        settings: Settings,
    ) -> None:
        self.settings = settings
        self.uri = settings.websocket_uri

        self.running = True
        self.finished = False

        self.frames: queue.Queue[Any] = queue.Queue(
            maxsize=settings.websocket_queue_size
        )

        self.messages_received = 0
        self.received_frames = 0
        self.invalid_frames = 0

        self.generated_frame_number = 0
        self.started_at = time.perf_counter()

        self.thread = threading.Thread(
            target=self._run,
            name="rtmaps-websocket-receiver",
            daemon=True,
        )

        self.thread.start()

    def _run(self) -> None:
        try:
            asyncio.run(
                self._receiver()
            )

        except Exception:
            logger.exception(
                "Unhandled error in RTMaps "
                "WebSocket receiver thread"
            )

        finally:
            self._finish_stream()

    async def _receiver(self) -> None:
        logger.info(
            "Connecting to RTMaps WebSocket %s",
            self.uri,
        )

        try:
            async with connect(
                self.uri,
                max_size=self.settings.websocket_max_size,
                compression=None,
                ping_interval=20,
                ping_timeout=20,
                open_timeout=(
                    self.settings
                    .websocket_connection_timeout
                ),
            ) as websocket:
                logger.info(
                    "Connected to RTMaps WebSocket %s",
                    self.uri,
                )

                async for message in websocket:
                    if not self.running:
                        break

                    self.messages_received += 1

                    if isinstance(message, str):
                        received_frame, stop = (
                            self._decode_text_message(
                                message
                            )
                        )

                        if stop:
                            break
                    else:
                        received_frame = (
                            self._decode_binary_message(
                                message
                            )
                        )

                    if received_frame is None:
                        continue

                    inserted = self._insert_frame(
                        received_frame
                    )

                    if not inserted:
                        break

                    self.received_frames += 1

                    if self.settings.websocket_send_ack:
                        await websocket.send(
                            json.dumps(
                                {
                                    "type": "ack",
                                    "frame": (
                                        received_frame.number
                                    ),
                                },
                                separators=(",", ":"),
                            )
                        )

                    if self.received_frames % 100 == 0:
                        logger.info(
                            "RTMaps frames received=%d",
                            self.received_frames,
                        )

        except ConnectionRefusedError:
            logger.exception(
                "RTMaps WebSocket refused the "
                "connection at %s",
                self.uri,
            )

        except TimeoutError:
            logger.exception(
                "Timed out connecting to RTMaps "
                "WebSocket %s",
                self.uri,
            )

        except ConnectionClosed as exc:
            if exc.code == 1000:
                logger.info(
                    "RTMaps WebSocket closed normally"
                )
            else:
                logger.warning(
                    "RTMaps WebSocket closed: "
                    "code=%s reason=%s",
                    exc.code,
                    exc.reason,
                )

        except Exception:
            logger.exception(
                "RTMaps WebSocket receiver failed"
            )

    def _next_generated_metadata(
        self,
    ) -> tuple[int, float]:
        self.generated_frame_number += 1

        timestamp = (
            time.perf_counter()
            - self.started_at
        )

        return (
            self.generated_frame_number,
            timestamp,
        )

    def _decode_text_message(
        self,
        message: str,
    ) -> tuple[VideoFrame | None, bool]:
        try:
            payload = json.loads(message)

        except json.JSONDecodeError:
            # Also support a plain Base64 JPEG string.
            frame = self._decode_jpeg_bytes(
                self._decode_base64(message)
            )

            if frame is None:
                self.invalid_frames += 1
                return None, False

            frame_number, timestamp = (
                self._next_generated_metadata()
            )

            return (
                VideoFrame(
                    number=frame_number,
                    timestamp=timestamp,
                    image=frame,
                ),
                False,
            )

        message_type = payload.get("type")

        if message_type == "stream_start":
            logger.info(
                "RTMaps stream started: %s",
                payload,
            )
            return None, False

        if message_type in {
            "stream_end",
            "end_of_stream",
            "eos",
        }:
            logger.info(
                "RTMaps end-of-stream received: %s",
                payload,
            )
            return None, True

        if message_type == "error":
            logger.error(
                "RTMaps WebSocket error: %s",
                payload.get("message"),
            )
            return None, True

        base64_image = (
            payload.get("camera_image_b64")
            or payload.get("image")
            or payload.get("data")
            or payload.get("frame_data")
        )

        if not isinstance(base64_image, str):
            logger.warning(
                "RTMaps JSON message contains "
                "no Base64 image field"
            )

            self.invalid_frames += 1
            return None, False

        image_bytes = self._decode_base64(
            base64_image
        )

        frame = self._decode_jpeg_bytes(
            image_bytes
        )

        if frame is None:
            self.invalid_frames += 1
            return None, False

        generated_number, generated_timestamp = (
            self._next_generated_metadata()
        )

        frame_number = self._safe_int(
            payload.get(
                "frame",
                payload.get(
                    "frame_number",
                    payload.get(
                        "sequence",
                        generated_number,
                    ),
                ),
            ),
            generated_number,
        )

        timestamp = self._safe_float(
            payload.get(
                "timestamp",
                payload.get(
                    "timestamp_seconds",
                    generated_timestamp,
                ),
            ),
            generated_timestamp,
        )

        return (
            VideoFrame(
                number=frame_number,
                timestamp=timestamp,
                image=frame,
            ),
            False,
        )

    def _decode_binary_message(
        self,
        message: bytes,
    ) -> VideoFrame | None:
        if not message:
            logger.warning(
                "Received empty binary message "
                "from RTMaps"
            )

            self.invalid_frames += 1
            return None

        # First try:
        # JSON metadata + newline + JPEG bytes.
        separator_index = message.find(b"\n")

        if separator_index > 0:
            metadata_bytes = message[
                :separator_index
            ]

            image_bytes = message[
                separator_index + 1:
            ]

            try:
                metadata = json.loads(
                    metadata_bytes.decode("utf-8")
                )

                frame = self._decode_jpeg_bytes(
                    image_bytes
                )

                if frame is None:
                    self.invalid_frames += 1
                    return None

                generated_number, generated_timestamp = (
                    self._next_generated_metadata()
                )

                frame_number = self._safe_int(
                    metadata.get(
                        "frame",
                        metadata.get(
                            "frame_number",
                            generated_number,
                        ),
                    ),
                    generated_number,
                )

                timestamp = self._safe_float(
                    metadata.get(
                        "timestamp",
                        metadata.get(
                            "timestamp_seconds",
                            generated_timestamp,
                        ),
                    ),
                    generated_timestamp,
                )

                return VideoFrame(
                    number=frame_number,
                    timestamp=timestamp,
                    image=frame,
                )

            except (
                UnicodeDecodeError,
                json.JSONDecodeError,
            ):
                # It may simply be a raw JPEG containing
                # a newline byte. Continue with raw decoding.
                pass

        # Second try: raw JPEG/PNG bytes.
        frame = self._decode_jpeg_bytes(
            message
        )

        if frame is None:
            self.invalid_frames += 1
            return None

        frame_number, timestamp = (
            self._next_generated_metadata()
        )

        return VideoFrame(
            number=frame_number,
            timestamp=timestamp,
            image=frame,
        )

    @staticmethod
    def _decode_base64(
        encoded_value: str,
    ) -> bytes | None:
        try:
            # Support data URLs such as:
            # data:image/jpeg;base64,/9j/4AAQ...
            if encoded_value.startswith("data:"):
                _, encoded_value = (
                    encoded_value.split(",", 1)
                )

            return base64.b64decode(
                encoded_value,
                validate=True,
            )

        except (
            ValueError,
            TypeError,
            base64.binascii.Error,
        ) as exc:
            logger.warning(
                "Invalid Base64 RTMaps frame: %s",
                exc,
            )
            return None

    @staticmethod
    def _decode_jpeg_bytes(
        image_bytes: bytes | None,
    ) -> Any | None:
        if not image_bytes:
            logger.warning(
                "RTMaps image payload is empty"
            )
            return None

        image_array = np.frombuffer(
            image_bytes,
            dtype=np.uint8,
        )

        if image_array.size == 0:
            logger.warning(
                "RTMaps image array is empty"
            )
            return None

        frame = cv2.imdecode(
            image_array,
            cv2.IMREAD_COLOR,
        )

        if frame is None:
            logger.warning(
                "OpenCV could not decode RTMaps frame"
            )
            return None

        if frame.size == 0:
            logger.warning(
                "RTMaps decoded frame has zero size"
            )
            return None

        return frame

    def _insert_frame(
        self,
        received_frame: VideoFrame,
    ) -> bool:
        while self.running:
            try:
                self.frames.put(
                    received_frame,
                    timeout=0.5,
                )

                return True

            except queue.Full:
                logger.debug(
                    "Frame queue full; waiting for FER"
                )

        return False

    @staticmethod
    def _safe_int(
        value: Any,
        default: int,
    ) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _safe_float(
        value: Any,
        default: float,
    ) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _finish_stream(self) -> None:
        if self.finished:
            return

        self.finished = True

        # Preserve items already queued. The end marker is placed
        # after them, so FER consumes every queued frame first.
        while True:
            try:
                self.frames.put(
                    _END_OF_STREAM,
                    timeout=0.5,
                )
                break

            except queue.Full:
                if not self.running:
                    try:
                        self.frames.get_nowait()
                        self.frames.task_done()
                    except queue.Empty:
                        pass

        self.running = False

        logger.info(
            "RTMaps WebSocket input finished: "
            "messages=%d valid_frames=%d "
            "invalid_frames=%d",
            self.messages_received,
            self.received_frames,
            self.invalid_frames,
        )

    def read(self) -> VideoFrame | None:
        item = self.frames.get()

        try:
            if item is _END_OF_STREAM:
                logger.info(
                    "All queued RTMaps frames consumed"
                )
                return None

            return item

        finally:
            self.frames.task_done()

    def release(self) -> None:
        self.running = False

        if (
            self.thread.is_alive()
            and self.thread
            is not threading.current_thread()
        ):
            self.thread.join(timeout=2.0)

        logger.info(
            "RTMaps WebSocket video source released"
        )