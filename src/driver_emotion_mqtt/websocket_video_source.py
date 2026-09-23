from __future__ import annotations

import asyncio
import base64
import logging
import queue
import threading
from typing import Any

import cv2
import numpy as np
import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)

# Marker inserted after the final frame.
_END_OF_STREAM = object()


class WebSocketVideoSource:
    def __init__(
        self,
        host: str,
        port: int,
        queue_size: int = 10,
    ) -> None:
        self.uri = f"ws://{host}:{port}"
        self.running = True
        self.finished = False

        # FIFO queue prevents new frames from overwriting unread frames.
        self.frames: queue.Queue[Any] = queue.Queue(
            maxsize=queue_size
        )

        self.received_frames = 0

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
            self._finish_stream()

    async def _receiver(self) -> None:
        try:
            async with websockets.connect(
                self.uri,
                ping_interval=None,
            ) as websocket:
                logger.info(
                    "Connected to WebSocket %s",
                    self.uri,
                )

                while self.running:
                    try:
                        message = await websocket.recv()

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

                        break

                    frame = self._decode_frame(message)

                    if frame is None:
                        continue

                    self.received_frames += 1

                    if self.received_frames % 100 == 0:
                        logger.info(
                            "WebSocket frames received=%d",
                            self.received_frames,
                        )

                    # Wait if FER is slower than the WebSocket sender.
                    # This preserves frames instead of overwriting them.
                    while self.running:
                        try:
                            self.frames.put(
                                frame,
                                timeout=0.5,
                            )
                            break

                        except queue.Full:
                            logger.debug(
                                "Frame queue full; "
                                "waiting for video processor"
                            )

        except ConnectionRefusedError:
            logger.exception(
                "Unable to connect to WebSocket %s",
                self.uri,
            )

        except Exception:
            logger.exception(
                "WebSocket receiver failed"
            )

        finally:
            self._finish_stream()

    @staticmethod
    def _decode_frame(
        message: str | bytes,
    ) -> Any | None:
        try:
            if isinstance(message, str):
                image_bytes = base64.b64decode(
                    message,
                    validate=True,
                )
            else:
                image_bytes = message

            if not image_bytes:
                logger.warning(
                    "Received empty WebSocket payload"
                )
                return None

            image_array = np.frombuffer(
                image_bytes,
                dtype=np.uint8,
            )

            if image_array.size == 0:
                logger.warning(
                    "Received empty image array"
                )
                return None

            frame = cv2.imdecode(
                image_array,
                cv2.IMREAD_COLOR,
            )

            if frame is None:
                logger.warning(
                    "OpenCV could not decode received frame"
                )
                return None

            if frame.size == 0:
                logger.warning(
                    "Received zero-size decoded frame"
                )
                return None

            # This return was missing in your current script.
            return frame

        except (ValueError, TypeError) as exc:
            logger.warning(
                "Invalid Base64 frame payload: %s",
                exc,
            )
            return None

        except Exception as exc:
            logger.warning(
                "Invalid frame received: %s",
                exc,
            )
            return None

    def _finish_stream(self) -> None:
        if self.finished:
            return

        self.finished = True
        self.running = False

        # This marker is inserted after all frames already queued.
        # read() receives it only after consuming every queued frame.
        while True:
            try:
                self.frames.put(
                    _END_OF_STREAM,
                    timeout=0.5,
                )
                break

            except queue.Full:
                # The processor is still consuming queued frames.
                continue

        logger.info(
            "WebSocket input ended after receiving %d frames",
            self.received_frames,
        )

    def read(self) -> Any | None:
        item = self.frames.get()

        if item is _END_OF_STREAM:
            logger.info(
                "All queued WebSocket frames have been consumed"
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