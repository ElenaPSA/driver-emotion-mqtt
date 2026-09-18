from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _as_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class Settings:
    video_path: Path = field(
        default_factory=lambda: Path(os.getenv("VIDEO_PATH", "output.mp4"))
    )
    output_dir: Path = field(
        default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "outputs"))
    )
    mqtt_host: str = field(
        default_factory=lambda: os.getenv("MQTT_BROKER", "127.0.0.1")
    )
    mqtt_port: int = field(
        default_factory=lambda: int(os.getenv("MQTT_PORT", "1883"))
    )
    mqtt_topic: str = field(
        default_factory=lambda: os.getenv(
            "MQTT_TOPIC", "telemetry/DriverEmotionState"
        )
    )
    mqtt_client_id: str = "driver-emotion-detector"
    mqtt_qos: int = 1
    mqtt_retain: bool = False
    mqtt_keepalive: int = 60
    mqtt_connection_timeout: float = 10.0
    process_every_n_frames: int = field(
        default_factory=lambda: int(os.getenv("PROCESS_EVERY_N_FRAMES", "1"))
    )
    display_video: bool = field(
        default_factory=lambda: _as_bool("DISPLAY_VIDEO", True)
    )
    use_mtcnn: bool = field(
        default_factory=lambda: _as_bool("USE_MTCNN", True)
    )
    start_embedded_broker: bool = field(
        default_factory=lambda: _as_bool("START_EMBEDDED_BROKER", True)
    )
    log_every_n_frames: int = 1

    @property
    def captured_emotions_path(self) -> Path:
        return self.output_dir / "captured_emotions.json"

    @property
    def dominant_emotions_path(self) -> Path:
        return self.output_dir / "dominant_emotion.json"

    def validate(self) -> None:
        if self.process_every_n_frames < 1:
            raise ValueError("PROCESS_EVERY_N_FRAMES must be at least 1")
        if not 0 <= self.mqtt_qos <= 2:
            raise ValueError("MQTT QoS must be between 0 and 2")
