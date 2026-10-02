## Driver Emotion MQTT
## Real-Time Emotion Detection Using Laptop Webcam and MQTT

---

# Overview

This project performs **real-time driver emotion recognition** using a laptop webcam.

Each frame captured from the webcam is analyzed using the FER (Facial Emotion Recognition) library.

The dominant emotion is then published to an MQTT broker.

The project is now fully local and does not use:

- RTMaps
- WebSockets
- Remote servers
- Video files

The processing pipeline runs entirely on the local machine.

---

# Final Architecture

```text
┌────────────────────────┐
│      Laptop Webcam     │
└────────────┬───────────┘
             │
             ▼
┌────────────────────────┐
│   video_processor.py   │
│                        │
│ OpenCV VideoCapture    │
│ Frame Acquisition      │
│ Frame Display          │
└────────────┬───────────┘
             │
             ▼
┌────────────────────────┐
│ emotion_detector.py    │
│                        │
│ FER                    │
│ MTCNN Face Detection   │
│ Emotion Recognition    │
└────────────┬───────────┘
             │
             ▼
┌────────────────────────┐
│ mqtt_publisher.py      │
│                        │
│ JSON Formatting        │
│ MQTT Publication       │
└────────────┬───────────┘
             │
             ▼
┌────────────────────────┐
│ MQTT Broker            │
│ aMQTT or Mosquitto     │
└────────────────────────┘
```

---

# Processing Flow

For every webcam frame:

```text
Camera Frame
     │
     ▼
OpenCV Capture
     │
     ▼
Emotion Detection
     │
     ▼
MQTT Publication
     │
     ▼
MQTT Subscriber
```

---

# Project Structure

```text
driver-emotion-mqtt/
│
├── outputs/
│
└── src/
    └── driver_emotion_mqtt/
        │
        ├── broker.py
        ├── config.py
        ├── emotion_detector.py
        ├── main.py
        ├── mqtt_publisher.py
        ├── serialization.py
        └── video_processor.py
```

---

# Unused Files

The following files are no longer required:

```text
websocket_video_source.py
video_stream_server.py
rtmaps_simulator.py
rtmaps_bridge_server.py
```

They can be:

- deleted
- archived
- kept for future experiments

---

# Component Description

---

## main.py

Application entry point.

Responsibilities:

- Load configuration
- Start MQTT broker
- Start video processing
- Handle application shutdown

Execution:

```bash
python -m driver_emotion_mqtt.main
```

---

## config.py

Contains all project settings.

Examples:

```python
camera_index
camera_width
camera_height
camera_fps

mqtt_host
mqtt_port

process_every_n_frames

display_video
```

---

## video_processor.py

Main orchestration component.

Responsibilities:

- Open webcam
- Acquire frames
- Run emotion detection
- Publish MQTT messages
- Display live video

The webcam is opened using:

```python
cv2.VideoCapture(
    settings.camera_index
)
```

Each frame is acquired using:

```python
success, frame = capture.read()
```

If the frame is valid:

```python
detector.analyze(frame)
```

is executed.

---

## emotion_detector.py

Responsible for emotion recognition.

Uses:

```python
FER(mtcnn=True)
```

Input:

```python
OpenCV image
```

Output:

```python
dominant emotion
confidence
```

Example:

```json
{
    "dominant_emotion": "happy",
    "confidence": 0.91
}
```

---

## mqtt_publisher.py

Responsible for messaging.

Publishes:

```json
{
    "frame": 152,
    "timestamp": 5.21,
    "dominant_emotion": "happy",
    "confidence": 0.91
}
```

Topic:

```text
telemetry/DriverEmotionState
```

---

## broker.py

Embedded MQTT broker.

Automatically started when:

```python
START_EMBEDDED_BROKER=true
```

Otherwise:

```text
External Mosquitto broker
```

is used.

---

## serialization.py

Utility functions.

Responsibilities:

```text
JSON conversion
JSON serialization
JSON persistence
```

---

# Installation

## Step 1 - Install Python

Verify:

```powershell
python --version
```

Expected:

```text
Python 3.x.x
```

---

## Step 2 - Open Project

Open:

```text
VS Code
```

Select:

```text
File
 → Open Folder
```

Choose:

```text
driver-emotion-mqtt
```

---

## Step 3 - Create Virtual Environment

Open terminal:

```powershell
python -m venv .venv
```

Activate:

```powershell
.venv\Scripts\activate
```

Expected:

```text
(.venv)
```

appears at the beginning of the terminal.

---

## Step 4 - Install Dependencies

```powershell
pip install ^
opencv-python ^
numpy ^
paho-mqtt ^
amqtt ^
fer ^
tensorflow ^
mtcnn
```

Verify:

```powershell
pip list
```

---

# Configuration

Open PowerShell terminal.

---

## Python Package Path

```powershell
$env:PYTHONPATH="src"
```

---

## Camera Configuration

Laptop integrated webcam:

```powershell
$env:CAMERA_INDEX="0"
```

External USB camera:

```powershell
$env:CAMERA_INDEX="1"
```

Resolution:

```powershell
$env:CAMERA_WIDTH="640"

$env:CAMERA_HEIGHT="480"
```

FPS:

```powershell
$env:CAMERA_FPS="10"
```

---

## Processing Configuration

Process every frame:

```powershell
$env:PROCESS_EVERY_N_FRAMES="1"
```

Process one frame out of two:

```powershell
$env:PROCESS_EVERY_N_FRAMES="2"
```

---

## Display

Enable video display:

```powershell
$env:DISPLAY_VIDEO="true"
```

Disable display:

```powershell
$env:DISPLAY_VIDEO="false"
```

---

## Face Detection

Use MTCNN:

```powershell
$env:USE_MTCNN="true"
```

---

## MQTT Configuration

Host:

```powershell
$env:MQTT_BROKER="127.0.0.1"
```

Port:

```powershell
$env:MQTT_PORT="1883"
```

---

## Embedded MQTT Broker

Enable embedded broker:

```powershell
$env:START_EMBEDDED_BROKER="true"
```

Disable embedded broker:

```powershell
$env:START_EMBEDDED_BROKER="false"
```

---

# Running The Application

Start the application:

```powershell
python -m driver_emotion_mqtt.main
```

---

# Expected Logs

```text
Starting embedded aMQTT broker

Opening local camera index=0

Camera opened

Initializing FER detector

Connecting to MQTT broker

Local webcam processing started
```

Then:

```text
Frame=1 | emotion=happy

Frame=2 | emotion=neutral

Frame=3 | emotion=sad
```

---

# Visualizing MQTT Messages

## Option 1 - MQTT Explorer (Recommended)

Install MQTT Explorer.

Connect:

```text
Host : 127.0.0.1
Port : 1883
```

Browse:

```text
telemetry
└── DriverEmotionState
```

Live messages appear automatically.

---

## Option 2 - Python MQTT Monitor

Create:

```text
mqtt_monitor.py
```

```python
import paho.mqtt.client as mqtt

def on_connect(client, userdata, flags,
               reason_code, properties=None):
    client.subscribe("#")

def on_message(client, userdata, msg):
    print()
    print("TOPIC:", msg.topic)
    print("MESSAGE:", msg.payload.decode())

client = mqtt.Client(
    callback_api_version=
    mqtt.CallbackAPIVersion.VERSION2
)

client.on_connect = on_connect
client.on_message = on_message

client.connect(
    "127.0.0.1",
    1883,
    60,
)

client.loop_forever()
```

Run:

```powershell
python mqtt_monitor.py
```

---

# Example MQTT Message

```json
{
    "frame": 152,
    "timestamp": 12.372,
    "dominant_emotion": "happy",
    "confidence": 0.91
}
```

---

# Stopping The Application

Click in the OpenCV window.

Press:

```text
Q
```

or

```text
ESC
```

The application will:

- release the webcam
- disconnect MQTT
- save JSON outputs
- stop cleanly

---

# Final Production Flow

```text
Laptop Webcam
      │
      ▼
OpenCV VideoCapture
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
MQTT Broker
      │
      ▼
MQTT Explorer / Subscribers
```

This is the simplest possible architecture: direct webcam acquisition, real-time facial emotion recognition, and MQTT publication, all running locally on your laptop.