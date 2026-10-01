## Installation

## Prerequisites

Required software:

- Python 3.10+
- RTMaps
- Git
- MQTT Broker (Mosquitto or embedded aMQTT)

Verify Python version:

```bash
python3 --version
```

---

# Clone Repository

```bash
git clone <repository>
cd driver-emotion-mqtt
```

---

# Create Virtual Environment

Create the virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

Linux:

```bash
source .venv/bin/activate
```

Windows:

```powershell
.venv\Scripts\activate
```

---

# Install the Project

The project uses:

```text
pyproject.toml
```

Install the package and all dependencies:

```bash
pip install --upgrade pip

pip install -e .
```

The option:

```bash
-e
```

installs the package in editable mode.

This allows modifying the source code without reinstalling the package after every change.

---

# Verify Installation

Verify that the package is visible:

```bash
python -c "import driver_emotion_mqtt; print('OK')"
```

Expected output:

```text
OK
```

---

# Project Layout

```text
driver-emotion-mqtt/
│
├── pyproject.toml
│
├── outputs/
│
└── src/
    └── driver_emotion_mqtt/
        │
        ├── main.py
        ├── config.py
        ├── websocket_video_source.py
        ├── video_processor.py
        ├── emotion_detector.py
        ├── mqtt_publisher.py
        ├── broker.py
        └── serialization.py
```

---

# Environment Configuration

## WebSocket

RTMaps runs the WebSocket server.

If RTMaps runs on the same machine:

```bash
export WEBSOCKET_URI='ws://127.0.0.1:8765/socket'
```

If RTMaps runs on another machine:

```bash
export WEBSOCKET_URI='ws://RTMAPS_HOST:8765/socket'
```

---

## MQTT

```bash
export MQTT_BROKER=127.0.0.1

export MQTT_PORT=1883
```

---

## Frame Processing

Analyse every frame:

```bash
export PROCESS_EVERY_N_FRAMES=1
```

---

## Acknowledgements

Recommended:

```bash
export WEBSOCKET_SEND_ACK=true
```

RTMaps waits for a frame acknowledgement before removing it from its transmission queue.

This prevents silent frame loss.

---

## Video Display

Optional:

```bash
export DISPLAY_VIDEO=true
```

Displays:

- face bounding boxes
- detected emotion
- confidence score

---

# Running the Emotion Detector

Activate the environment:

```bash
source .venv/bin/activate
```

Start the application:

```bash
python -m driver_emotion_mqtt.main
```

Expected logs:

```text
Connecting to RTMaps WebSocket

Connected to RTMaps WebSocket

Initializing FER detector

Connected to MQTT broker
```

---

# Development Installation

If new dependencies are added to:

```text
pyproject.toml
```

reinstall the package:

```bash
pip install -e .
```

---

# Upgrade Dependencies

```bash
pip install --upgrade pip

pip install -e .
```