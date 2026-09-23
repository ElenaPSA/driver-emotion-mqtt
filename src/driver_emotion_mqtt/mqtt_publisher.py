from __future__ import annotations

import json
import logging
import threading
from typing import Any

import paho.mqtt.client as mqtt

from .config import Settings
from .serialization import to_json_value

logger = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.connected = threading.Event()
        self.connection_error: str | None = None
        self.started = False
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id=settings.mqtt_client_id,
            protocol=mqtt.MQTTv311,
        )
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

    def _on_connect(
        self, client: mqtt.Client, userdata: Any, flags: Any,
        reason_code: Any, properties: Any = None,
    ) -> None:
        if reason_code == 0:
            logger.info("Connected to MQTT broker %s:%d", self.settings.mqtt_host,
                        self.settings.mqtt_port)
        else:
            self.connection_error = str(reason_code)
            logger.error("MQTT connection failed: %s", reason_code)
        self.connected.set()

    def _on_disconnect(
        self, client: mqtt.Client, userdata: Any, disconnect_flags: Any,
        reason_code: Any, properties: Any = None,
    ) -> None:
        self.connected.clear()
        if reason_code != 0:
            logger.warning("Unexpected MQTT disconnection: %s", reason_code)

    def connect(self) -> None:
        self.connection_error = None
        self.connected.clear()
        self.client.connect(
            self.settings.mqtt_host,
            self.settings.mqtt_port,
            keepalive=self.settings.mqtt_keepalive,
        )
        self.client.loop_start()
        self.started = True

        if not self.connected.wait(self.settings.mqtt_connection_timeout):
            self.disconnect()
            raise TimeoutError("Timed out connecting to the MQTT broker")
        if self.connection_error:
            self.disconnect()
            raise ConnectionError(self.connection_error)

    def publish(
    self,
    payload: dict[str, Any],
) -> bool:
    if not self.connected.is_set():
        logger.error(
            "Cannot publish because MQTT is disconnected"
        )
        return False

    message = json.dumps(
        to_json_value(payload),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )

    result = self.client.publish(
        self.settings.mqtt_topic,
        message,
        qos=self.settings.mqtt_qos,
        retain=self.settings.mqtt_retain,
    )

    if result.rc != mqtt.MQTT_ERR_SUCCESS:
        logger.error(
            "MQTT publish failed with code %s",
            result.rc,
        )
        return False

    try:
        result.wait_for_publish(
            timeout=self.settings.mqtt_connection_timeout
        )
    except RuntimeError as exc:
        logger.error(
            "MQTT publication failed: %s",
            exc,
        )
        return False

    if not result.is_published():
        logger.error(
            "MQTT publication was not confirmed"
        )
        return False

    return True

    def disconnect(self) -> None:
        if not self.started:
            return
        try:
            self.client.disconnect()
        finally:
            self.client.loop_stop()
            self.connected.clear()
            self.started = False
