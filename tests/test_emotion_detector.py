from driver_emotion_mqtt.emotion_detector import DriverEmotionDetector


def test_largest_face_is_selected() -> None:
    detections = [
        {"box": [0, 0, 10, 10]},
        {"box": [0, 0, 30, 20]},
    ]
    assert DriverEmotionDetector._largest_face(detections) == detections[1]
