from __future__ import annotations

import asyncio
import logging

from .broker import create_broker
from .config import Settings
from .video_processor import process_video

logger = logging.getLogger(__name__)


async def main() -> None:
    settings = Settings()
    broker = create_broker(settings.mqtt_port) if settings.start_embedded_broker else None
    broker_started = False

    try:
        if broker is not None:
            logger.info("Starting embedded aMQTT broker on port %d", settings.mqtt_port)
            await broker.start()
            broker_started = True
        await asyncio.to_thread(process_video, settings)
    finally:
        if broker is not None and broker_started:
            logger.info("Stopping embedded aMQTT broker")
            await broker.shutdown()


def run() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
    )
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Application terminated by user")
