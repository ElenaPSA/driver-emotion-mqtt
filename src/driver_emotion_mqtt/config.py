from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _as_bool(
    name: str,
    default: bool,
) -> bool:
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
    # Output
    # ---------------------------------------------------------
    output_dir: Path = field(
        default_factory=lambda: Path(
            os.getenv(
                "OUTPUT_DIR",
                "outputs",
            )
        )
    )

    # ---------------------------------------------------------
    # RTMaps WebSocket source
    # ---------------------------------------------------------
    websocket_uri: str = field(
        default_factory=lambda: os.getenv(
            "WEBSOCKET_URI",
            "ws://127.0.0.1:8765/socket",
        )
    )

    websocket_queue_size: int = field(
        default_factory=lambda: int(
            os.getenv(
                "WEBSOCKET_QUEUE_SIZE",
                "10",
            )
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

    websocket_connection_timeout: float = field(
        default_factory=lambda: float(
            os.getenv(
                "WEBSOCKET_CONNECTION_TIMEOUT",
                "10.0",
            )
        )
    )

    websocket_send_ack: bool = field(
        default_factory=lambda: _as_bool(
            "WEBSOCKET_SEND_ACK",
            True,
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
            os.getenv(
                "MQTT_PORT",
                "1883",
            )
        )
    )

    mqtt_topic: str = field(
        default_factory=lambda: os.getenv(
            "MQTT_TOPIC",
            "telemetry/DriverEmotionState",
        )
    )

    mqtt_client_id: str = field(
        default_factory=lambda: os.getenv(
            "MQTT_CLIENT_ID",
            "driver-emotion-detector",
        )
    )

    mqtt_qos: int = field(
        default_factory=lambda: int(
            os.getenv(
                "MQTT_QOS",
                "1",
            )
        )
    )

    mqtt_retain: bool = field(
        default_factory=lambda: _as_bool(
            "MQTT_RETAIN",
            False,
        )
    )

    mqtt_keepalive: int = 60
    mqtt_connection_timeout: float = 10.0

    # ---------------------------------------------------------
    # Emotion detection
    # ---------------------------------------------------------
    process_every_n_frames: int = field(
        default_factory=lambda: int(
            os.getenv(
                "PROCESS_EVERY_N_FRAMES",
                "1",
            )
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

    log_every_n_frames: int = field(
        default_factory=lambda: int(
            os.getenv(
                "LOG_EVERY_N_FRAMES",
                "1",
            )
        )
    )

    # ---------------------------------------------------------
    # Broker
    # ---------------------------------------------------------
    start_embedded_broker: bool = field(
        default_factory=lambda: _as_bool(
            "START_EMBEDDED_BROKER",
            True,
        )
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
        if not self.websocket_uri.startswith(
            ("ws://", "wss://")
        ):
            raise ValueError(
                "WEBSOCKET_URI must start with "
                "ws:// or wss://"
            )

        if self.websocket_queue_size < 1:
            raise ValueError(
                "WEBSOCKET_QUEUE_SIZE must be at least 1"
            )

        if self.websocket_max_size < 1:
            raise ValueError(
                "WEBSOCKET_MAX_SIZE must be positive"
            )

        if self.websocket_connection_timeout <= 0:
            raise ValueError(
                "WEBSOCKET_CONNECTION_TIMEOUT "
                "must be positive"
            )

        if self.websocket_reconnect_delay < 0:
            raise ValueError(
                "WEBSOCKET_RECONNECT_DELAY "
                "cannot be negative"
            )

        if self.process_every_n_frames < 1:
            raise ValueError(
                "PROCESS_EVERY_N_FRAMES "
                "must be at least 1"
            )

        if not 0 <= self.mqtt_qos <= 2:
            raise ValueError(
                "MQTT QoS must be between 0 and 2"
            )

        if self.log_every_n_frames < 0:
            raise ValueError(
                "LOG_EVERY_N_FRAMES cannot be negative"
            )