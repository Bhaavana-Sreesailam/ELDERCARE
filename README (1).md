# ElderCare Guardian

A wearable emergency-monitoring and alert system for independent senior citizens.

ElderCare Guardian continuously watches **heart rate** and **motion**, automatically
detects **falls** and **abnormal heart rates**, raises **real-time emergency alerts**
to a caregiver, and presents everything on a calm, readable **web dashboard**.

> ⚠️ **This is a student / prototype project for demonstration and education only.
> It is not a certified medical device and is not a substitute for emergency
> services or professional medical care.**

---

## What's in the box

The whole software stack is here and **runs today with no hardware** — a built-in
simulator stands in for the wearable so you can see the system working end to end.
When you have the ESP32 and sensors, flash the included firmware and it streams to
the same server.

```
ElderCare-Guardian/
├── app.py                 # Flask server: API + dashboard
├── config.py              # Thresholds, patient defaults, email settings
├── database.py            # SQLite storage (patients, readings, alerts)
├── fall_detection.py      # Free-fall → impact fall-detection state machine
├── alert_engine.py        # Abnormal-condition checks + caregiver notifications
├── analytics.py           # Pandas trends + wellness indicators
├── simulator.py           # Virtual wearable (no hardware needed)
├── requirements.txt
├── templates/             # dashboard.html, patient.html, base.html
├── static/                # CSS, dashboard JS, vendored Bootstrap + Chart.js
└── firmware/
    └── eldercare_esp32.ino  # ESP32 Arduino firmware for the real device
```

---

## Quick start (software only — no hardware)

You need **Python 3.10+**.

```bash
# 1. (optional but recommended) create a virtual environment
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate

# 2. install dependencies
pip install -r requirements.txt

# 3. start the server
python app.py
```

Now open **http://localhost:5000** in your browser. The dashboard loads with a
default patient ("Margaret Doyle") and an empty history.

To bring it to life, open a **second terminal** and run the simulator:

```bash
# backfill 24h of history, then stream live readings once per second
python simulator.py --seed 24
```

Refresh the dashboard — you'll see the heart-rate trend fill in and the live BPM
update every few seconds.

### Try the emergency scenarios

Stop the simulator (Ctrl-C) and run one of these to watch an alert fire:

```bash
python simulator.py --scenario fall     # simulate a fall (free-fall + impact)
python simulator.py --scenario tachy     # abnormally high heart rate
python simulator.py --scenario brady     # abnormally low heart rate
python simulator.py --chaos              # random events over time
```

When an alert triggers, the entire status panel turns red, the heartbeat icon
switches to an alarm pulse, and the event appears in the **Alert log**, where a
caregiver can mark it resolved.

---

## The dashboard

- **Current status** — an at-a-glance, plain-language verdict ("All is well" /
  "Needs attention" / "Emergency"), the live heart rate, and a beating heart
  whose colour and pulse reflect the person's current state.
- **Stat cards** — resting heart rate, today's range, a 0–100 wellness indicator,
  and current movement state.
- **Heart-rate trend** — a 6-hour / 24-hour / 7-day chart.
- **Alert log** — recent alerts with severity, with a one-click *resolve*.
- **Patient page** — edit the patient's details and the caregiver's contact info.

The design deliberately uses warm, low-anxiety colours and reserves red strictly
for genuine emergencies, so a glance is always meaningful.

---

## Enabling real caregiver email alerts (optional)

By default, alerts are recorded and shown on the dashboard. To also **email** the
caregiver when an emergency fires, set these environment variables before starting
the server (example uses a Gmail App Password):

```bash
export ELDERCARE_SMTP_HOST="smtp.gmail.com"
export ELDERCARE_SMTP_PORT="587"
export ELDERCARE_SMTP_USER="you@gmail.com"
export ELDERCARE_SMTP_PASSWORD="your_app_password"
export ELDERCARE_SMTP_FROM="you@gmail.com"     # optional; defaults to SMTP_USER
python app.py
```

Email sends to the **caregiver email** set on the Patient page. If these variables
aren't set, the app runs normally and simply skips sending mail. The alert engine
is structured so an SMS provider (e.g. Twilio) can be added the same way.

---

## Using the real hardware (ESP32 + sensors)

### Parts & wiring

| Component | Role | ESP32 connection |
|-----------|------|------------------|
| **ESP32** | microcontroller / Wi-Fi | — |
| **MAX30102** | heart-rate sensor | 3V3, GND, SDA→GPIO21, SCL→GPIO22 |
| **MPU6050** | motion sensor (accelerometer) | 3V3, GND, SDA→GPIO21, SCL→GPIO22 |

Both sensors share the same two I2C pins (they have different addresses).
**Power the breakouts from 3V3, not 5V.**

### Flashing

1. Install the **Arduino IDE** and the **esp32** boards package (Espressif).
2. In Library Manager, install:
   - *SparkFun MAX3010x Pulse and Proximity Sensor Library*
   - *Adafruit MPU6050* and *Adafruit Unified Sensor*
   - *ArduinoJson*
3. Open `firmware/eldercare_esp32.ino` and set:
   - `WIFI_SSID` / `WIFI_PASS`
   - `SERVER_URL` — the LAN IP of the machine running `app.py`,
     e.g. `http://192.168.1.50:5000/api/sensor-data`
   - `DEVICE_ID` — must match a patient on the server (default `eldercare-001`)
4. Select your board and port, then upload.

The wearable connects to Wi-Fi and POSTs a reading roughly once per second. The
server runs the authoritative fall-detection and alert logic, so the dashboard
behaves identically whether data comes from the simulator or the real device.

---

## How it works

```
 MAX30102 + MPU6050  →  ESP32  →  Flask API  →  SQLite  →  Web dashboard → Alerts
```

- **Sensor data collection** — the ESP32 reads heart rate and 3-axis acceleration
  and sends JSON to the server.
- **Storage** — SQLite keeps patients, every reading, and every alert.
- **Fall detection** — a magnitude-based state machine looks for the
  characteristic free-fall dip followed by an impact spike.
- **Alert engine** — checks heart rate against configurable bands and the fall
  flag, applies a per-alert cooldown, records the event, and optionally emails
  the caregiver.
- **Dashboard & analytics** — the browser polls the API; Pandas computes resting
  rate, ranges, hourly/daily trends, and a wellness indicator.

All thresholds (heart-rate bands, fall sensitivity, alert cooldown) live in
`config.py` and can be tuned in one place.

---

## Future enhancement: ML-based anomaly detection

The data pipeline is ready for **scikit-learn**: with enough stored readings you
could train a per-person model (e.g. Isolation Forest) to flag subtle deviations
from someone's *normal* pattern, beyond fixed thresholds. Uncomment `scikit-learn`
in `requirements.txt` to start experimenting. This is intentionally left as an
optional next step.

---

## A note on safety

ElderCare Guardian is a prototype built for learning. Fixed thresholds and simple
heuristics are not clinically validated, sensor breakouts are not medical-grade,
and no monitoring software should be relied upon for life-safety. Always keep real
emergency contacts and services in place.
