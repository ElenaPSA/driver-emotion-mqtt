from driver_emotion_mqtt.config import Settings


def test_default_settings_are_valid() -> None:
    Settings().validate()
