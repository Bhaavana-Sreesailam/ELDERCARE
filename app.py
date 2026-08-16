"""
ElderCare Guardian - Flask application.

This ties everything together:

  * Receives sensor data from the ESP32 (or the simulator) at /api/sensor-data
  * Runs fall detection and the alert engine on every reading
  * Serves a live dashboard and a patient page
  * Exposes JSON endpoints the dashboard polls for real-time updates

Run it with:  python app.py
Then open:     http://localhost:5000
"""

from flask import Flask, jsonify, render_template, request

import analytics
import config
import database as db
from alert_engine import evaluate
from fall_detection import FallDetector, classify_impact, magnitude

app = Flask(__name__)

# One fall detector per device, kept in memory between requests.
_detectors = {}


def detector_for(device_id):
    if device_id not in _detectors:
        _detectors[device_id] = FallDetector()
    return _detectors[device_id]


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    patient = db.get_patient()
    return render_template("dashboard.html", patient=patient)


@app.route("/patient")
def patient_page():
    patient = db.get_patient()
    return render_template("patient.html", patient=patient)


# ---------------------------------------------------------------------------
# Ingest: the wearable posts here
# ---------------------------------------------------------------------------
@app.route("/api/sensor-data", methods=["POST"])
def sensor_data():
    """
    Accept one reading from the device. Expected JSON:
        {
          "device_id": "eldercare-001",
          "heart_rate": 72,
          "spo2": 97,            # optional
          "accel_x": 0.02,       # in g
          "accel_y": -0.01,
          "accel_z": 0.99
        }
    The accelerometer magnitude is computed server-side. A device may also
    send "fall": true if it ran its own quick on-board impact check.
    """
    data = request.get_json(silent=True) or {}
    device_id = data.get("device_id", config.DEFAULT_PATIENT["device_id"])

    ax = float(data.get("accel_x", 0.0))
    ay = float(data.get("accel_y", 0.0))
    az = float(data.get("accel_z", 1.0))
    mag = magnitude(ax, ay, az)
    hr = data.get("heart_rate")
    hr = float(hr) if hr is not None else None
    spo2 = data.get("spo2")
    spo2 = float(spo2) if spo2 is not None else None

    # Store the reading.
    db.insert_reading(
        device_id=device_id, heart_rate=hr, spo2=spo2,
        accel_x=ax, accel_y=ay, accel_z=az, accel_magnitude=mag,
    )

    # Fall detection: trust an explicit device flag, otherwise run our own.
    fall = bool(data.get("fall", False)) or detector_for(device_id).update(mag)

    # Evaluate alerts.
    patient = db.get_patient(device_id) or db.get_patient()
    reading = {"device_id": device_id, "heart_rate": hr, "accel_magnitude": mag}
    alerts = evaluate(reading, fall_detected=fall, patient=patient)

    return jsonify({
        "status": "ok",
        "magnitude": round(mag, 3),
        "motion": classify_impact(mag),
        "fall_detected": fall,
        "alerts_raised": alerts,
    })


# ---------------------------------------------------------------------------
# Read: the dashboard polls these
# ---------------------------------------------------------------------------
@app.route("/api/current")
def api_current():
    """Latest reading + active alerts + headline analytics, for the live view."""
    latest = db.get_latest_reading()
    active = db.get_alerts(limit=10, only_active=True)
    return jsonify({
        "reading": latest,
        "active_alerts": active,
        "summary": analytics.summary(hours=24),
        "patient": db.get_patient(),
    })


@app.route("/api/history")
def api_history():
    hours = int(request.args.get("hours", 24))
    return jsonify({
        "hourly": analytics.hourly_trend(hours=hours),
        "daily": analytics.daily_trend(days=7),
    })


@app.route("/api/alerts")
def api_alerts():
    return jsonify({"alerts": db.get_alerts(limit=50)})


@app.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
def api_resolve(alert_id):
    db.resolve_alert(alert_id)
    return jsonify({"status": "resolved", "id": alert_id})


@app.route("/api/patient", methods=["POST"])
def api_update_patient():
    """Save edits from the patient page."""
    d = request.get_json(silent=True) or request.form
    db.upsert_patient(
        device_id=d.get("device_id"),
        name=d.get("name"),
        age=int(d["age"]) if d.get("age") else None,
        conditions=d.get("conditions"),
        contact_name=d.get("contact_name"),
        contact_phone=d.get("contact_phone"),
        contact_email=d.get("contact_email"),
        address=d.get("address"),
    )
    return jsonify({"status": "saved"})


if __name__ == "__main__":
    db.init_db()
    print("ElderCare Guardian running at http://localhost:5000")
    print(f"Email alerts: {'ENABLED' if config.EMAIL_ENABLED else 'disabled (dashboard-only)'}")
    app.run(host="0.0.0.0", port=5000, debug=True)
