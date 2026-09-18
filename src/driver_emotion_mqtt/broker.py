from __future__ import annotations

from typing import Any

from amqtt.broker import Broker


def create_broker_config(host: str, port: int) -> dict[str, Any]:
    return {
        "listeners": {
            "default": {"type": "tcp", "bind": f"{host}:{port}"}
        },
        "sys_interval": 0,
        "plugins": {
            "amqtt.plugins.authentication.AnonymousAuthPlugin": {
                "allow_anonymous": True
            }
        },
        "topic_check": {"enabled": False},
    }


def create_broker(port: int) -> Broker:
    return Broker(create_broker_config("0.0.0.0", port))
