# Driver Emotion MQTT

Detect facial emotions in a driver-facing video, publish per-frame telemetry over MQTT, and save complete and dominant-emotion results as JSON.

## Architecture

- `config.py`: typed environment-based settings
- `broker.py`: optional embedded aMQTT broker
- `mqtt_publisher.py`: Paho MQTT lifecycle and publishing
- `emotion_detector.py`: FER inference and driver-face selection
- `video_processor.py`: OpenCV processing pipeline
- `main.py`: async application lifecycle and CLI

## Requirements

- Python 3.10 to 3.12
- A video file, or adjust `VIDEO_PATH`
- A desktop session when `DISPLAY_VIDEO=true`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
pip install -e ".[dev]"
```

## Run with the embedded broker

```bash
cp .env.example .env
# Environment variables may be exported manually; .env is an example only.
export VIDEO_PATH=output.mp4
export START_EMBEDDED_BROKER=true
driver-emotion
```

Or:

```bash
python -m driver_emotion_mqtt
```

## Connect to an external Mosquitto broker

```bash
export START_EMBEDDED_BROKER=false
export MQTT_BROKER=192.168.1.20
export MQTT_PORT=1883
python -m driver_emotion_mqtt
```

Example subscriber:

```bash
mosquitto_sub -h 127.0.0.1 -p 1883 -t 'telemetry/DriverEmotionState' -v
```

## Headless execution

```bash
export DISPLAY_VIDEO=false
python -m driver_emotion_mqtt
```

## Tests and linting

```bash
pytest
ruff check .
```

## Output

Files are written under `outputs/` by default:

- `captured_emotions.json`
- `dominant_emotion.json`

Press `q` or `Esc` to stop when video display is enabled.
