# Driver Emotion MQTT - RTMaps Integration

## Overview

Driver Emotion MQTT is a real-time emotion recognition pipeline designed to receive video frames through a WebSocket connection, detect driver emotions using FER (Facial Emotion Recognition), and publish emotion data to MQTT.

The system supports two operating modes:

1. **Simulation mode**
   - Video frames come from `rtmaps_simulator.py`
   - Used during development and testing.

2. **Production mode**
   - Video frames come from a real RTMaps diagram.
   - RTMaps acquires images from an external camera and sends them through a WebSocket.

---

# High-Level Architecture

## Simulation Mode

```text
output.mp4
     │
     ▼
rtmaps_simulator.py
     │
     │ WebSocket
     ▼
websocket_video_source.py
     │
     ▼
video_processor.py
     │
     ▼
emotion_detector.py
     │
     ▼
mqtt_publisher.py
     │
     ▼
Mosquitto / aMQTT
```

---

## Production Mode (RTMaps)

```text
External Camera
     │
     ▼
RTMaps Camera Component
     │
     ▼
RTMaps Python Component
     │
     │ WebSocket
     ▼
websocket_video_source.py
     │
     ▼
video_processor.py
     │
     ▼
emotion_detector.py
     │
     ▼
mqtt_publisher.py
     │
     ▼
Mosquitto / aMQTT
```

The only component replaced is:

```text
rtmaps_simulator.py
```

which becomes:

```text
RTMaps Python Component
```

Everything else remains unchanged.

---

# Project Structure

```text
driver-emotion-mqtt/
│
├── output.mp4
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
        ├── serialization.py
        ├── rtmaps_simulator.py
        └── video_stream_server.py
```

---

# Application Flow

For every frame:

```text
Camera Frame
      │
      ▼
JPEG Encoding
      │
      ▼
WebSocket
      │
      ▼
Frame Reconstruction
      │
      ▼
Emotion Detection
      │
      ▼
MQTT Publication
```

---

# Components Description

---

## main.py

### Purpose

Application entry point.

### Responsibilities

- Load configuration
- Start MQTT broker (optional)
- Start video processing
- Handle application shutdown

### Execution

```bash
python3 -m driver_emotion_mqtt.main
```

---

## config.py

### Purpose

Centralized application configuration.

### Examples

```python
websocket_uri
mqtt_host
mqtt_port
mqtt_topic
process_every_n_frames
display_video
```

---

## websocket_video_source.py

### Purpose

Receives images from RTMaps through WebSocket.

### Responsibilities

- Connect to RTMaps WebSocket
- Receive image payloads
- Decode Base64 images
- Decode JPEG images
- Create VideoFrame objects
- Store frames in an internal queue

### Output

```python
VideoFrame(
    number,
    timestamp,
    image
)
```

Used by:

```python
video_processor.py
```

---

## video_processor.py

### Purpose

Main processing orchestrator.

### Responsibilities

- Read frames
- Call FER
- Build MQTT payload
- Publish emotion information
- Save JSON outputs

### Processing loop

```python
frame = source.read()

detections = detector.analyze(frame)

publisher.publish(...)
```

---

## emotion_detector.py

### Purpose

FER (Facial Emotion Recognition).

### Input

OpenCV image.

### Output

Example:

```json
{
  "dominant_emotion": "happy",
  "confidence": 0.92
}
```

### Supported emotions

```text
Angry
Disgust
Fear
Happy
Sad
Surprise
Neutral
```

---

## mqtt_publisher.py

### Purpose

Publish FER results through MQTT.

### Example Payload

```json
{
  "frame": 152,
  "timestamp": 5.47,
  "dominant_emotion": "happy",
  "confidence": 0.92
}
```

### Topic

```text
telemetry/DriverEmotionState
```

---

## broker.py

### Purpose

Embedded MQTT broker.

Used only when:

```python
start_embedded_broker = True
```

Otherwise Mosquitto is used.

---

## serialization.py

### Purpose

Save and load JSON data.

Example:

```python
save_json(...)
```

---

# Simulation Mode

## Purpose

Allows testing without RTMaps.

### Architecture

```text
Video File
     │
     ▼
rtmaps_simulator.py
     │
     ▼
WebSocket
```

The simulator behaves exactly like RTMaps.

---

## Starting Simulator

Terminal 1:

```bash
python3 -m driver_emotion_mqtt.rtmaps_simulator \
    --source output.mp4 \
    --host 127.0.0.1 \
    --port 8765
```

Terminal 2:

```bash
python3 -m driver_emotion_mqtt.main
```

---

# RTMaps Integration

## RTMaps Diagram

Recommended structure:

```text
External Camera
       │
       ▼
Camera Component
       │
       ▼
RTMaps Python Component
       │
       ▼
WebSocket
```

---

# RTMaps WebSocket Payload

The RTMaps component should send one message per frame:

```json
{
  "type": "frame",
  "frame": 123,
  "timestamp": 4.56,
  "camera_image_b64": "..."
}
```

Where:

```text
frame
```

is frame number.

```text
timestamp
```

is acquisition time.

```text
camera_image_b64
```

contains JPEG image encoded in Base64.

---

# Required Modification For Real RTMaps

## websocket_video_source.py

Find:

```python
base64_image = (
    payload.get("image")
    or payload.get("data")
    or payload.get("frame_data")
)
```

Replace with:

```python
base64_image = (
    payload.get("camera_image_b64")
    or payload.get("image")
    or payload.get("data")
    or payload.get("frame_data")
)
```

This modification is required because RTMaps uses:

```json
camera_image_b64
```

to transport the image.

---

# Migration From Simulator To RTMaps

## Current

```text
output.mp4
      │
      ▼
rtmaps_simulator.py
      │
      ▼
WebSocket
      │
      ▼
FER Pipeline
```

---

## Future

```text
External Camera
      │
      ▼
RTMaps
      │
      ▼
WebSocket
      │
      ▼
FER Pipeline
```

Only the frame producer changes.

---

# Installation

## Create Virtual Environment

```bash
python3 -m venv driver-emotion

source driver-emotion/bin/activate
```

---

## Install Dependencies

```bash
pip install \
    opencv-python \
    numpy \
    websockets \
    paho-mqtt \
    amqtt \
    fer \
    tensorflow \
    mtcnn
```

---

# Configuration

Example:

```bash
export WEBSOCKET_URI='ws://127.0.0.1:8765'

export MQTT_BROKER='127.0.0.1'

export MQTT_PORT=1883

export MQTT_TOPIC='telemetry/DriverEmotionState'

export PROCESS_EVERY_N_FRAMES=1

export DISPLAY_VIDEO=false

export WEBSOCKET_SEND_ACK=false
```

---

# Running The Application

## Simulation Mode

Terminal 1:

```bash
python3 -m driver_emotion_mqtt.rtmaps_simulator
```

Terminal 2:

```bash
python3 -m driver_emotion_mqtt.main
```

---

## Production Mode

1. Start Mosquitto.
2. Start RTMaps diagram.
3. Run:

```bash
python3 -m driver_emotion_mqtt.main
```

---

# MQTT Output Example

```json
{
  "frame": 225,
  "timestamp": 8.322,
  "dominant_emotion": "happy",
  "confidence": 0.91
}
```

Published to:

```text
telemetry/DriverEmotionState
```

---

# Final Production Architecture

```text
External Camera
      │
      ▼
RTMaps Camera Component
      │
      ▼
RTMaps Python Component
      │
      ▼
WebSocket
      │
      ▼
websocket_video_source.py
      │
      ▼
video_processor.py
      │
      ▼
emotion_detector.py
      │
      ▼
mqtt_publisher.py
      │
      ▼
Mosquitto
```

Only the frame producer changes between simulation and production.

The FER and MQTT pipeline remains exactly the same.