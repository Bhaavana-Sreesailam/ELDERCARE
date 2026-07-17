"""
ElderCare Guardian - Alert engine.

This is the brain that decides when something is wrong and who to tell.
Given a fresh reading (and a fall flag from the detector) it:

  1. Checks the heart rate against the warning / emergency bands.
  2. Checks whether a fall was detected.
  3. Records an alert in the database (so it shows on the dashboard).
  4. Sends an email to the caregiver, if email is configured.

A per-alert-type cooldown stops a single event from firing dozens of
duplicate notifications.
"""

import smtplib
import ssl
from datetime import datetime, timedelta
from email.message import EmailMessage

import config
import database as db


def _cooldown_active(device_id, alert_type):
    """True if we've already fired this alert type very recently."""
    last = db.last_alert_time(device_id, alert_type)
    if last is None:
        return False
    return datetime.utcnow() - last < timedelta(seconds=config.ALERT_COOLDOWN_SECONDS)


def _send_email(patient, alert_type, severity, message, heart_rate):
    """Email the caregiver. Returns True if sent, False if skipped/failed."""
    if not config.EMAIL_ENABLED:
        return False

    to_addr = (patient or {}).get("contact_email")
    if not to_addr:
        return False

    name = (patient or {}).get("name", "the monitored person")
    subject = f"[{severity.upper()}] ElderCare alert for {name}: {alert_type}"

    body = (
        f"An ElderCare Guardian alert was triggered.\n\n"
        f"Person:    {name}\n"
        f"Severity:  {severity.upper()}\n"
        f"Type:      {alert_type}\n"
        f"Detail:    {message}\n"
    )
    if heart_rate:
        body += f"Heart rate: {heart_rate:.0f} bpm\n"
    if patient:
        body += (
            f"\nContact on file: {patient.get('contact_name', '-')} "
            f"({patient.get('contact_phone', '-')})\n"
            f"Address: {patient.get('address', '-')}\n"
        )
    body += f"\nTime (UTC): {datetime.utcnow().isoformat(timespec='seconds')}\n"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.SMTP_FROM
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT) as server:
            server.starttls(context=context)
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.send_message(msg)
        return True
    except Exception as exc:  # never let a mail failure crash monitoring
        print(f"[alert_engine] email send failed: {exc}")
        return False


def _raise_alert(device_id, patient, alert_type, severity, message, heart_rate):
    """Record an alert and notify, respecting the cooldown."""
    if _cooldown_active(device_id, alert_type):
        return None

    alert_id = db.insert_alert(
        device_id=device_id,
        alert_type=alert_type,
        severity=severity,
        message=message,
        heart_rate=heart_rate,
    )
    sent = _send_email(patient, alert_type, severity, message, heart_rate)
    flag = "email sent" if sent else ("email off" if not config.EMAIL_ENABLED
                                      else "email skipped")
    print(f"[ALERT] {severity.upper():9} {alert_type:16} {message}  ({flag})")
    return alert_id


def evaluate(reading, fall_detected, patient=None):
    """
    Main entry point. Inspect one reading and raise any warranted alerts.

    `reading` is a dict with at least: device_id, heart_rate, accel_magnitude.
    `fall_detected` is the boolean from FallDetector.update().
    Returns a list of the alert dicts that were raised this call.
    """
    device_id = reading["device_id"]
    hr = reading.get("heart_rate")
    raised = []

    # ---- Fall ----------------------------------------------------------
    if fall_detected:
        alert_id = _raise_alert(
            device_id, patient,
            alert_type="fall",
            severity="emergency",
            message="Possible fall detected (free-fall followed by impact).",
            heart_rate=hr,
        )
        if alert_id:
            raised.append({"id": alert_id, "type": "fall", "severity": "emergency"})

    # ---- Heart rate ----------------------------------------------------
    # Ignore 0 / nonsense readings (no finger on the sensor).
    if hr is not None and hr >= config.HR_VALID_MIN:
        if hr <= config.HR_EMERGENCY_LOW:
            sev, msg = "emergency", f"Critically low heart rate ({hr:.0f} bpm)."
        elif hr >= config.HR_EMERGENCY_HIGH:
            sev, msg = "emergency", f"Critically high heart rate ({hr:.0f} bpm)."
        elif hr <= config.HR_WARNING_LOW:
            sev, msg = "warning", f"Low heart rate ({hr:.0f} bpm)."
        elif hr >= config.HR_WARNING_HIGH:
            sev, msg = "warning", f"Elevated heart rate ({hr:.0f} bpm)."
        else:
            sev = msg = None

        if sev:
            alert_id = _raise_alert(
                device_id, patient,
                alert_type=f"heart_rate_{sev}",
                severity=sev,
                message=msg,
                heart_rate=hr,
            )
            if alert_id:
                raised.append({"id": alert_id, "type": "heart_rate", "severity": sev})

    return raised
