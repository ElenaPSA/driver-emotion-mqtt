from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)

    if value is None:
        return default

    return value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@dataclass(frozen=True, slots=True)
class Settings:
    # ---------------------------------------------------------
    # Video file used by video_stream_server.py
    # ---------------------------------------------------------
    video_path: Path = field(
        default_factory=lambda: Path(
            os.getenv("VIDEO_PATH", "output.mp4")
        )
    )

    output_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv("OUTPUT_DIR", "outputs")
        )
    )

    # ---------------------------------------------------------
    # WebSocket
    # ---------------------------------------------------------
    websocket_host: str = field(
        default_factory=lambda: os.getenv(
            "WEBSOCKET_HOST",
            "127.0.0.1",
        )
    )

    websocket_port: int = field(
        default_factory=lambda: int(
            os.getenv("WEBSOCKET_PORT", "8765")
        )
    )

    websocket_queue_size: int = field(
        default_factory=lambda: int(
            os.getenv("WEBSOCKET_QUEUE_SIZE", "10")
        )
    )

    websocket_max_size: int = field(
        default_factory=lambda: int(
            os.getenv(
                "WEBSOCKET_MAX_SIZE",
                str(16 * 1024 * 1024),
            )
        )
    )

    jpeg_quality: int = field(
        default_factory=lambda: int(
            os.getenv("JPEG_QUALITY", "90")
        )
    )

    # ---------------------------------------------------------
    # MQTT
    # ---------------------------------------------------------
    mqtt_host: str = field(
        default_factory=lambda: os.getenv(
            "MQTT_BROKER",
            "127.0.0.1",
        )
    )

    mqtt_port: int = field(
        default_factory=lambda: int(
            os.getenv("MQTT_PORT", "1883")
        )
    )

    mqtt_topic: str = field(
        default_factory=lambda: os.getenv(
            "MQTT_TOPIC",
            "telemetry/DriverEmotionState",
        )
    )

    mqtt_client_id: str = "driver-emotion-detector"
    mqtt_qos: int = 1
    mqtt_retain: bool = False
    mqtt_keepalive: int = 60
    mqtt_connection_timeout: float = 10.0

    # ---------------------------------------------------------
    # Processing
    # ---------------------------------------------------------
    process_every_n_frames: int = field(
        default_factory=lambda: int(
            os.getenv("PROCESS_EVERY_N_FRAMES", "1")
        )
    )

    display_video: bool = field(
        default_factory=lambda: _as_bool(
            "DISPLAY_VIDEO",
            False,
        )
    )

    use_mtcnn: bool = field(
        default_factory=lambda: _as_bool(
            "USE_MTCNN",
            True,
        )
    )

    # False means that an external Mosquitto broker must be running.
    start_embedded_broker: bool = field(
        default_factory=lambda: _as_bool(
            "START_EMBEDDED_BROKER",
            True,
        )
    )

    log_every_n_frames: int = field(
        default_factory=lambda: int(
            os.getenv("LOG_EVERY_N_FRAMES", "1")
        )
    )

    @property
    def websocket_uri(self) -> str:
        return (
            f"ws://{self.websocket_host}:"
            f"{self.websocket_port}"
        )

    @property
    def captured_emotions_path(self) -> Path:
        return (
            self.output_dir
            / "captured_emotions.json"
        )

    @property
    def dominant_emotions_path(self) -> Path:
        return (
            self.output_dir
            / "dominant_emotion.json"
        )

    def validate(self) -> None:
        if self.process_every_n_frames < 1:
            raise ValueError(
                "PROCESS_EVERY_N_FRAMES must be at least 1"
            )

        if not 0 <= self.mqtt_qos <= 2:
            raise ValueError(
                "MQTT QoS must be between 0 and 2"
            )

        if self.websocket_queue_size < 1:
            raise ValueError(
                "WEBSOCKET_QUEUE_SIZE must be at least 1"
            )

        if self.websocket_max_size < 1:
            raise ValueError(
                "WEBSOCKET_MAX_SIZE must be positive"
            )

        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError(
                "JPEG_QUALITY must be between 1 and 100"
            )