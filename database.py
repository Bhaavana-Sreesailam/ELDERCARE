"""
ElderCare Guardian - Database layer (SQLite).

Three tables:
  patients  - who is being monitored and who to contact
  readings  - every sensor sample (heart rate + accelerometer)
  alerts    - emergencies that were detected

All access goes through the helper functions here so the rest of the
app never writes raw SQL.
"""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta

import config


@contextmanager
def get_db():
    """Open a connection with dict-style rows and always close it."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    """Create tables if they don't exist and seed a default patient."""
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id       TEXT UNIQUE NOT NULL,
                name            TEXT NOT NULL,
                age             INTEGER,
                conditions      TEXT,
                contact_name    TEXT,
                contact_phone   TEXT,
                contact_email   TEXT,
                address         TEXT
            );

            CREATE TABLE IF NOT EXISTS readings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id       TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                heart_rate      REAL,
                spo2            REAL,
                accel_x         REAL,
                accel_y         REAL,
                accel_z         REAL,
                accel_magnitude REAL
            );

            CREATE TABLE IF NOT EXISTS alerts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id       TEXT NOT NULL,
                timestamp       TEXT NOT NULL,
                alert_type      TEXT NOT NULL,
                severity        TEXT NOT NULL,
                message         TEXT NOT NULL,
                heart_rate      REAL,
                resolved        INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_readings_time
                ON readings (device_id, timestamp);
            CREATE INDEX IF NOT EXISTS idx_alerts_time
                ON alerts (device_id, timestamp);
            """
        )

    # Seed default patient if the table is empty.
    if get_patient() is None:
        p = config.DEFAULT_PATIENT
        upsert_patient(
            device_id=p["device_id"],
            name=p["name"],
            age=p["age"],
            conditions=p["conditions"],
            contact_name=p["contact_name"],
            contact_phone=p["contact_phone"],
            contact_email=p["contact_email"],
            address=p["address"],
        )


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
def upsert_patient(device_id, name, age=None, conditions=None,
                   contact_name=None, contact_phone=None,
                   contact_email=None, address=None):
    """Insert a patient, or update them if the device_id already exists."""
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO patients
                (device_id, name, age, conditions, contact_name,
                 contact_phone, contact_email, address)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(device_id) DO UPDATE SET
                name=excluded.name,
                age=excluded.age,
                conditions=excluded.conditions,
                contact_name=excluded.contact_name,
                contact_phone=excluded.contact_phone,
                contact_email=excluded.contact_email,
                address=excluded.address
            """,
            (device_id, name, age, conditions, contact_name,
             contact_phone, contact_email, address),
        )


def get_patient(device_id=None):
    """Return one patient as a dict, or None. If no device_id, return the first."""
    with get_db() as conn:
        if device_id:
            row = conn.execute(
                "SELECT * FROM patients WHERE device_id = ?", (device_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM patients ORDER BY id LIMIT 1"
            ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Readings
# ---------------------------------------------------------------------------
def insert_reading(device_id, heart_rate, spo2, accel_x, accel_y, accel_z,
                   accel_magnitude, timestamp=None):
    timestamp = timestamp or datetime.utcnow().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO readings
                (device_id, timestamp, heart_rate, spo2,
                 accel_x, accel_y, accel_z, accel_magnitude)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (device_id, timestamp, heart_rate, spo2,
             accel_x, accel_y, accel_z, accel_magnitude),
        )
        return cur.lastrowid


def get_latest_reading(device_id=None):
    with get_db() as conn:
        if device_id:
            row = conn.execute(
                "SELECT * FROM readings WHERE device_id = ? "
                "ORDER BY id DESC LIMIT 1", (device_id,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM readings ORDER BY id DESC LIMIT 1"
            ).fetchone()
    return dict(row) if row else None


def get_readings_since(hours=24, device_id=None):
    """Return readings from the last `hours` hours, oldest first."""
    cutoff = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    with get_db() as conn:
        if device_id:
            rows = conn.execute(
                "SELECT * FROM readings WHERE device_id = ? AND timestamp >= ? "
                "ORDER BY timestamp ASC", (device_id, cutoff)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM readings WHERE timestamp >= ? "
                "ORDER BY timestamp ASC", (cutoff,)
            ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------
def insert_alert(device_id, alert_type, severity, message,
                 heart_rate=None, timestamp=None):
    timestamp = timestamp or datetime.utcnow().isoformat()
    with get_db() as conn:
        cur = conn.execute(
            """
            INSERT INTO alerts
                (device_id, timestamp, alert_type, severity, message, heart_rate)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (device_id, timestamp, alert_type, severity, message, heart_rate),
        )
        return cur.lastrowid


def get_alerts(limit=50, device_id=None, only_active=False):
    query = "SELECT * FROM alerts"
    clauses, params = [], []
    if device_id:
        clauses.append("device_id = ?")
        params.append(device_id)
    if only_active:
        clauses.append("resolved = 0")
    if clauses:
        query += " WHERE " + " AND ".join(clauses)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_db() as conn:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def last_alert_time(device_id, alert_type):
    """When was an alert of this type last fired? Used for cooldown."""
    with get_db() as conn:
        row = conn.execute(
            "SELECT timestamp FROM alerts WHERE device_id = ? AND alert_type = ? "
            "ORDER BY id DESC LIMIT 1", (device_id, alert_type)
        ).fetchone()
    return datetime.fromisoformat(row["timestamp"]) if row else None


def resolve_alert(alert_id):
    with get_db() as conn:
        conn.execute("UPDATE alerts SET resolved = 1 WHERE id = ?", (alert_id,))
