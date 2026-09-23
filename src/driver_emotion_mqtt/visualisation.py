import cv2
import json

VIDEO_FILE = "webcam_mia.mp4"
EMOTION_FILE = "outputs/captured_emotions.json"
DOMINANT_FILE = "outputs/dominant_emotion.json"
OUTPUT_VIDEO = "output_emotions_webcam_mia.mp4"

with open(EMOTION_FILE, "r", encoding="utf-8") as f:
    frame_emotions = json.load(f)

with open(DOMINANT_FILE, "r", encoding="utf-8") as f:
    dominant_data = json.load(f)

emotion_map = {
    item["frame"]: item
    for item in frame_emotions
}

dominant_map = {
    item["frame"]: item
    for item in dominant_data
}

cap = cv2.VideoCapture(VIDEO_FILE)

if not cap.isOpened():
    raise RuntimeError(
        f"Unable to open {VIDEO_FILE}"
    )

fps = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

writer = cv2.VideoWriter(
    OUTPUT_VIDEO,
    cv2.VideoWriter_fourcc(*"mp4v"),
    fps,
    (width, height),
)

frame_id = 0

while True:

    success, frame = cap.read()

    if not success:
        break

    frame_id += 1

    detections = emotion_map.get(
        frame_id,
        {}
    ).get(
        "emotions",
        []
    )

    dominant = dominant_map.get(
        frame_id,
        {}
    )

    dominant_emotion = dominant.get(
        "dominant_emotion",
        "unknown"
    )

    confidence = dominant.get(
        "confidence",
        None
    )

    timestamp = dominant.get(
        "timestamp",
        (frame_id - 1) / fps
    )

    # Draw face detections
    for detection in detections:

        box = detection.get(
            "box",
            None
        )

        if not box or len(box) < 4:
            continue

        x, y, w, h = map(
            int,
            box[:4]
        )

        cv2.rectangle(
            frame,
            (x, y),
            (x + w, y + h),
            (0, 255, 0),
            2,
        )

        if "emotions" in detection:

            face_emotions = detection["emotions"]

            best_emotion = max(
                face_emotions,
                key=face_emotions.get
            )

            best_score = face_emotions[
                best_emotion
            ]

            cv2.putText(
                frame,
                f"{best_emotion} {best_score:.2f}",
                (x, max(30, y - 10)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 255, 0),
                2,
                cv2.LINE_AA,
            )

    # Global info banner
    overlay = frame.copy()

    cv2.rectangle(
        overlay,
        (10, 10),
        (600, 100),
        (0, 0, 0),
        -1,
    )

    frame = cv2.addWeighted(
        overlay,
        0.4,
        frame,
        0.6,
        0,
    )

    cv2.putText(
        frame,
        f"Frame: {frame_id}",
        (20, 35),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )

    cv2.putText(
        frame,
        f"Time: {timestamp:.2f}s",
        (20, 65),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (255, 255, 255),
        2,
    )

    if confidence is not None:

        label = (
            f"Driver: "
            f"{dominant_emotion} "
            f"({confidence:.3f})"
        )

    else:

        label = (
            f"Driver: "
            f"{dominant_emotion}"
        )

    cv2.putText(
        frame,
        label,
        (20, 95),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (0, 255, 255),
        2,
    )

    writer.write(frame)

cap.release()
writer.release()

print()
print("Created:")
print(OUTPUT_VIDEO)
