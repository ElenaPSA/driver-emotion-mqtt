import asyncio
import json
import queue
import threading
import time
from typing import Any

import cv2
import rtmaps.types
from rtmaps.base_component import BaseComponent
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed


# ------------------------------------------------------------------
# Default configuration
# ------------------------------------------------------------------

DEFAULT_BIND_ADDRESS = "0.0.0.0"
DEFAULT_PORT = 8765
DEFAULT_IMAGE_MAX_WIDTH = 640
DEFAULT_JPEG_QUALITY = 70
DEFAULT_QUEUE_SIZE = 30

WEBSOCKET_MAX_SIZE = 16 * 1024 * 1024


class rtmaps_python(BaseComponent):
    """
    RTMaps component that:

    1. Receives images from an RTMaps camera component.
    2. JPEG-encodes every image.
    3. Hosts a WebSocket server.
    4. Sends one binary WebSocket message per frame.
    5. Waits for an acknowledgement before removing the frame
       from the queue.

    Binary message format:

        JSON metadata
        newline byte
        JPEG bytes
    """

    def __init__(self):
        BaseComponent.__init__(self)

        self._loop = None
        self._thread = None

        self._stopping = False

        self._bind_address = DEFAULT_BIND_ADDRESS
        self._port = DEFAULT_PORT

        # Optional additional application state.
        self._latest_state: dict[str, Any] = {}
        self._state_lock = threading.Lock()

        # The network thread peeks at the first item and removes
        # it only after successful transmission and acknowledgement.
        self._frame_buffer: list[
            tuple[int, bytes]
        ] = []

        self._frame_condition = threading.Condition()
        self._queue_size = DEFAULT_QUEUE_SIZE

        self._frame_number = 0
        self._started_at = 0.0

        # Diagnostics.
        self._frames_received = 0
        self._frames_encoded = 0
        self._frames_queued = 0
        self._frames_sent = 0
        self._encoding_failures = 0

        self._client_connected = False

    def Dynamic(self):
        # Optional JSON input containing additional state.
        self.add_input(
            "json_data",
            rtmaps.types.AUTO,
        )

        # Connect the RTMaps camera image output here.
        self.add_input(
            "camera_image",
            rtmaps.types.AUTO,
        )

        # Use 0.0.0.0 to accept remote connections.
        self.add_property(
            "bind_address",
            DEFAULT_BIND_ADDRESS,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "port",
            DEFAULT_PORT,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "image_max_width",
            DEFAULT_IMAGE_MAX_WIDTH,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "jpeg_quality",
            DEFAULT_JPEG_QUALITY,
            rtmaps.types.AUTO,
        )

        self.add_property(
            "queue_size",
            DEFAULT_QUEUE_SIZE,
            rtmaps.types.AUTO,
        )

        # The Python receiver must send one ACK per decoded
        # and queued frame when this property is True.
        self.add_property(
            "wait_for_ack",
            True,
            rtmaps.types.AUTO,
        )

    def Birth(self):
        self._bind_address = str(
            self.properties["bind_address"].data
        )

        self._port = int(
            self.properties["port"].data
        )

        self._queue_size = int(
            self.properties["queue_size"].data
        )

        image_max_width = int(
            self.properties["image_max_width"].data
        )

        jpeg_quality = int(
            self.properties["jpeg_quality"].data
        )

        if self._queue_size < 1:
            raise ValueError(
                "queue_size must be at least 1"
            )

        if image_max_width < 1:
            raise ValueError(
                "image_max_width must be positive"
            )

        if not 1 <= jpeg_quality <= 100:
            raise ValueError(
                "jpeg_quality must be between 1 and 100"
            )

        self._stopping = False
        self._latest_state = {}

        with self._frame_condition:
            self._frame_buffer.clear()

        self._frame_number = 0
        self._started_at = time.perf_counter()

        self._frames_received = 0
        self._frames_encoded = 0
        self._frames_queued = 0
        self._frames_sent = 0
        self._encoding_failures = 0

        self._client_connected = False

        self._loop = asyncio.new_event_loop()

        self._thread = threading.Thread(
            target=self._run_event_loop,
            name="rtmaps-websocket-server",
            daemon=True,
        )

        self._thread.start()

        print(
            "RTMaps WebSocket server starting: "
            f"ws://{self._bind_address}:{self._port}/socket, "
            f"queue_size={self._queue_size}, "
            f"jpeg_quality={jpeg_quality}, "
            f"image_max_width={image_max_width}"
        )

    def _run_event_loop(self):
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(
                self._server_main()
            )

        except Exception as exc:
            if not self._stopping:
                print(
                    "RTMaps WebSocket server error: "
                    f"{exc}"
                )

        finally:
            pending_tasks = asyncio.all_tasks(
                self._loop
            )

            for task in pending_tasks:
                task.cancel()

            if pending_tasks:
                self._loop.run_until_complete(
                    asyncio.gather(
                        *pending_tasks,
                        return_exceptions=True,
                    )
                )

    async def _server_main(self):
        async with serve(
            self._client_handler,
            self._bind_address,
            self._port,
            max_size=WEBSOCKET_MAX_SIZE,
            compression=None,
            ping_interval=20,
            ping_timeout=20,
        ) as server:
            print(
                "RTMaps WebSocket server listening on "
                f"ws://{self._bind_address}:"
                f"{self._port}/socket"
            )

            while not self._stopping:
                await asyncio.sleep(0.1)

            server.close()
            await server.wait_closed()

    async def _send_control_message(
        self,
        websocket,
        payload: dict[str, Any],
    ):
        await websocket.send(
            json.dumps(
                payload,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
        )

    async def _wait_for_ack(
        self,
        websocket,
        expected_frame: int,
    ):
        response = await websocket.recv()

        if not isinstance(response, str):
            raise RuntimeError(
                "Expected a text ACK from "
                "websocket_video_source.py"
            )

        payload = json.loads(response)

        if payload.get("type") != "ack":
            raise RuntimeError(
                "Expected an ACK, received: "
                f"{payload}"
            )

        acknowledged_frame = int(
            payload.get("frame", -1)
        )

        if acknowledged_frame != expected_frame:
            raise RuntimeError(
                "Incorrect ACK: "
                f"expected={expected_frame}, "
                f"received={acknowledged_frame}"
            )

    def _wait_for_next_frame(
        self,
    ) -> tuple[int, bytes] | None:
        """
        Wait for a frame without removing it.

        The frame remains at the front of the buffer until the
        WebSocket client acknowledges it.
        """
        with self._frame_condition:
            while (
                not self._frame_buffer
                and not self._stopping
            ):
                self._frame_condition.wait(
                    timeout=0.5
                )

            if self._stopping:
                return None

            return self._frame_buffer[0]

    def _mark_frame_sent(
        self,
        frame_number: int,
    ):
        with self._frame_condition:
            if not self._frame_buffer:
                return

            queued_number, _ = (
                self._frame_buffer[0]
            )

            if queued_number != frame_number:
                raise RuntimeError(
                    "Frame-buffer ordering error: "
                    f"expected={frame_number}, "
                    f"queued={queued_number}"
                )

            self._frame_buffer.pop(0)

            self._frame_condition.notify_all()

    async def _client_handler(
        self,
        websocket,
    ):
        if self._client_connected:
            print(
                "Rejecting second WebSocket client"
            )

            await websocket.close(
                code=1013,
                reason=(
                    "An emotion detector is "
                    "already connected"
                ),
            )

            return

        self._client_connected = True

        print(
            "Emotion detector connected to RTMaps: "
            f"{websocket.remote_address}"
        )

        try:
            await self._send_control_message(
                websocket,
                {
                    "type": "stream_start",
                    "source": (
                        "rtmaps-external-camera"
                    ),
                    "live": True,
                    "format": (
                        "json-metadata-newline-jpeg"
                    ),
                },
            )

            while not self._stopping:
                queued_frame = (
                    await asyncio.to_thread(
                        self._wait_for_next_frame
                    )
                )

                if queued_frame is None:
                    break

                frame_number, message = (
                    queued_frame
                )

                # Binary WebSocket message.
                await websocket.send(message)

                wait_for_ack = bool(
                    self.properties[
                        "wait_for_ack"
                    ].data
                )

                if wait_for_ack:
                    await self._wait_for_ack(
                        websocket,
                        expected_frame=frame_number,
                    )

                self._mark_frame_sent(
                    frame_number
                )

                self._frames_sent += 1

                if self._frames_sent % 100 == 0:
                    with self._frame_condition:
                        waiting_frames = len(
                            self._frame_buffer
                        )

                    print(
                        "RTMaps frames: "
                        f"received={self._frames_received}, "
                        f"encoded={self._frames_encoded}, "
                        f"queued={self._frames_queued}, "
                        f"sent={self._frames_sent}, "
                        f"waiting={waiting_frames}"
                    )

        except ConnectionClosed as exc:
            print(
                "Emotion detector disconnected: "
                f"code={exc.code}, "
                f"reason={exc.reason}"
            )

        except Exception as exc:
            if not self._stopping:
                print(
                    "RTMaps client-handler error: "
                    f"{exc}"
                )

        finally:
            self._client_connected = False

            print(
                "Emotion detector connection released"
            )

    def _update_json_state(self):
        if not self.has_data("json_data"):
            return

        raw_data = self.inputs[
            "json_data"
        ].ioelt.data

        try:
            if hasattr(
                raw_data,
                "tobytes",
            ):
                raw_bytes = raw_data.tobytes()

            elif isinstance(
                raw_data,
                bytes,
            ):
                raw_bytes = raw_data

            elif isinstance(
                raw_data,
                str,
            ):
                raw_bytes = raw_data.encode(
                    "utf-8"
                )

            else:
                raise TypeError(
                    "Unsupported json_data type: "
                    f"{type(raw_data).__name__}"
                )

            incoming_state = json.loads(
                raw_bytes.decode("utf-8")
            )

            if not isinstance(
                incoming_state,
                dict,
            ):
                raise ValueError(
                    "json_data must contain "
                    "a JSON object"
                )

        except Exception as exc:
            print(
                "Invalid RTMaps json_data input: "
                f"{exc}"
            )

            return

        with self._state_lock:
            self._latest_state = (
                incoming_state
            )

    def _prepare_camera_frame(
        self,
    ) -> tuple[int, bytes] | None:
        if not self.has_data(
            "camera_image"
        ):
            return None

        try:
            image_element = self.inputs[
                "camera_image"
            ].ioelt.data

            frame = image_element.image_data

        except Exception as exc:
            print(
                "Unable to retrieve RTMaps "
                f"camera image: {exc}"
            )

            return None

        if frame is None:
            print(
                "RTMaps camera image is None"
            )
            return None

        if (
            not hasattr(frame, "size")
            or frame.size == 0
        ):
            print(
                "RTMaps camera image is empty"
            )
            return None

        self._frames_received += 1

        # Ensure contiguous OpenCV-compatible memory.
        frame = frame.copy()

        height, width = frame.shape[:2]

        image_max_width = int(
            self.properties[
                "image_max_width"
            ].data
        )

        if width > image_max_width:
            scale = (
                image_max_width
                / float(width)
            )

            resized_width = image_max_width

            resized_height = max(
                1,
                int(round(height * scale)),
            )

            frame = cv2.resize(
                frame,
                (
                    resized_width,
                    resized_height,
                ),
                interpolation=cv2.INTER_AREA,
            )

        jpeg_quality = int(
            self.properties[
                "jpeg_quality"
            ].data
        )

        successful, encoded_image = (
            cv2.imencode(
                ".jpg",
                frame,
                [
                    int(
                        cv2.IMWRITE_JPEG_QUALITY
                    ),
                    jpeg_quality,
                ],
            )
        )

        if not successful:
            self._encoding_failures += 1

            print(
                "RTMaps could not encode "
                "camera frame "
                f"{self._frames_received}"
            )

            return None

        self._frames_encoded += 1
        self._frame_number += 1

        timestamp_seconds = (
            time.perf_counter()
            - self._started_at
        )

        with self._state_lock:
            metadata = (
                self._latest_state.copy()
            )

        metadata.update(
            {
                "type": "frame",
                "frame": self._frame_number,
                "timestamp": (
                    timestamp_seconds
                ),
                "image_format": "jpeg",
                "image_width": int(
                    frame.shape[1]
                ),
                "image_height": int(
                    frame.shape[0]
                ),
            }
        )

        metadata_bytes = json.dumps(
            metadata,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

        message = (
            metadata_bytes
            + b"\n"
            + encoded_image.tobytes()
        )

        return (
            self._frame_number,
            message,
        )

    def _queue_frame(
        self,
        queued_frame: tuple[int, bytes],
    ):
        """
        Block when the transmission queue is full.

        This applies backpressure instead of overwriting or
        silently dropping frames.
        """
        with self._frame_condition:
            while (
                len(self._frame_buffer)
                >= self._queue_size
                and not self._stopping
            ):
                print(
                    "RTMaps transmission queue is full: "
                    f"waiting="
                    f"{len(self._frame_buffer)}, "
                    f"sent={self._frames_sent}"
                )

                self._frame_condition.wait(
                    timeout=0.5
                )

            if self._stopping:
                return

            self._frame_buffer.append(
                queued_frame
            )

            self._frames_queued += 1

            self._frame_condition.notify_all()

    def Core(self):
        # Additional JSON state is optional.
        self._update_json_state()

        queued_frame = (
            self._prepare_camera_frame()
        )

        if queued_frame is None:
            return

        self._queue_frame(
            queued_frame
        )

    def Death(self):
        print(
            "Stopping RTMaps WebSocket server"
        )

        self._stopping = True

        with self._frame_condition:
            self._frame_condition.notify_all()

        if (
            self._loop is not None
            and self._loop.is_running()
        ):
            self._loop.call_soon_threadsafe(
                lambda: None
            )

        if self._thread is not None:
            self._thread.join(
                timeout=5
            )

        if (
            self._loop is not None
            and not self._loop.is_closed()
        ):
            self._loop.close()

        print(
            "RTMaps WebSocket server stopped: "
            f"received={self._frames_received}, "
            f"encoded={self._frames_encoded}, "
            f"queued={self._frames_queued}, "
            f"sent={self._frames_sent}, "
            f"encoding_failures="
            f"{self._encoding_failures}"
        )