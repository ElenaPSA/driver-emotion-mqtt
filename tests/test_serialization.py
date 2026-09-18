import math

from driver_emotion_mqtt.serialization import to_json_value


def test_non_finite_float_becomes_none() -> None:
    assert to_json_value(math.nan) is None


def test_nested_values_are_preserved() -> None:
    assert to_json_value({"values": (1, 2.5)}) == {"values": [1, 2.5]}
