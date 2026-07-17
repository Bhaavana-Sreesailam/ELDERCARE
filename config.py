"""
ElderCare Guardian - Central configuration.

Everything tunable lives here so you can adjust thresholds without
hunting through the codebase. Notification credentials are read from
environment variables so you never commit secrets.
"""

import os

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = os.environ.get("ELDERCARE_DB", "eldercare.db")

# ---------------------------------------------------------------------------
# Heart-rate thresholds (beats per minute)
#
# These are general reference values for a resting adult. They are NOT
# medical advice. A doctor should set the right bands for a specific person,
# since "normal" varies a lot with age, fitness and medication.
# ---------------------------------------------------------------------------
HR_EMERGENCY_LOW = 45      # below this = emergency (severe bradycardia)
HR_WARNING_LOW = 55        # below this = warning
HR_WARNING_HIGH = 110      # above this = warning
HR_EMERGENCY_HIGH = 130    # above this = emergency (severe tachycardia)

# A heart-rate reading of 0 usually means "no finger on the sensor",
# so we ignore readings below this when judging health.
HR_VALID_MIN = 30

# ---------------------------------------------------------------------------
# Fall detection (units are g, where 1 g = 9.81 m/s^2)
#
# A fall typically looks like: brief free-fall (acceleration drops toward 0 g)
# followed by a sharp impact spike (well above 1 g), then unusual stillness.
# ---------------------------------------------------------------------------
FREEFALL_THRESHOLD = 0.45      # below this magnitude = possible free-fall
IMPACT_THRESHOLD = 2.6         # above this magnitude = possible impact
FREEFALL_WINDOW = 12           # samples to look back for a free-fall before impact
INACTIVITY_THRESHOLD = 0.18    # |magnitude - 1g| below this = "still"

# ---------------------------------------------------------------------------
# Alert behaviour
# ---------------------------------------------------------------------------
# Don't re-fire the same kind of alert more often than this (seconds).
# Stops a single event from generating a flood of notifications.
ALERT_COOLDOWN_SECONDS = 60

# ---------------------------------------------------------------------------
# Email notifications (optional)
#
# To enable email alerts, set these environment variables before starting:
#   export ELDERCARE_SMTP_HOST=smtp.gmail.com
#   export ELDERCARE_SMTP_PORT=587
#   export ELDERCARE_SMTP_USER=you@gmail.com
#   export ELDERCARE_SMTP_PASSWORD=your_app_password
#   export ELDERCARE_SMTP_FROM=you@gmail.com
#
# If they're not set, alerts are still recorded and shown on the dashboard;
# only the email send is skipped.
# ---------------------------------------------------------------------------
SMTP_HOST = os.environ.get("ELDERCARE_SMTP_HOST")
SMTP_PORT = int(os.environ.get("ELDERCARE_SMTP_PORT", "587"))
SMTP_USER = os.environ.get("ELDERCARE_SMTP_USER")
SMTP_PASSWORD = os.environ.get("ELDERCARE_SMTP_PASSWORD")
SMTP_FROM = os.environ.get("ELDERCARE_SMTP_FROM", SMTP_USER)

EMAIL_ENABLED = all([SMTP_HOST, SMTP_USER, SMTP_PASSWORD])

# ---------------------------------------------------------------------------
# Default patient (seeded into the DB on first run if none exists).
# Edit this on the Patient page later, or change it here before first run.
# ---------------------------------------------------------------------------
DEFAULT_PATIENT = {
    "name": "Margaret Doyle",
    "age": 78,
    "conditions": "Hypertension, mild arrhythmia",
    "device_id": "eldercare-001",
    "contact_name": "Sarah Doyle (daughter)",
    "contact_phone": "+1-555-0142",
    "contact_email": "caregiver@example.com",
    "address": "14 Birchwood Lane, Apartment 3",
}
