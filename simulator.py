"""
ElderCare Guardian - Wearable simulator.

Lets you run and demo the whole system with no hardware. It posts realistic
heart-rate and accelerometer data to the running Flask server exactly the way
the ESP32 firmware will, so the dashboard, alerts and analytics all work.

Usage
-----
Start the server first (python app.py), then in another terminal:

    python simulator.py                  # stream normal data forever
    python simulator.py --seed 24        # backfill 24h of history, then stream
    python simulator.py --scenario fall  # inject one fall, then keep streaming
    python simulator.py --scenario tachy # inject a high-heart-rate episode
    python simulator.py --scenario brady # inject a low-heart-rate episode
    python simulator.py --chaos          # occasionally inject random events

Press Ctrl+C to stop.
"""

import argparse
import math
import random
import time
from datetime import datetime, timedelta

import requests

import config
import database as db

import os
SERVER = os.environ.get("ELDERCARE_SERVER", "http://localhost:5000/api/sensor-data")
DEVICE_ID = config.DEFAULT_PATIENT["device_id"]


# ---------------------------------------------------------------------------
# Signal generators
# ---------------------------------------------------------------------------
def normal_hr(t):
    """A gently wandering resting heart rate around ~72 bpm."""
    base = 72 + 6 * math.sin(t / 40.0)        # slow drift
    return round(base + random.gauss(0, 1.5), 1)


def still_accel():
    """Wearer at rest: ~1 g downward with small sensor noise."""
    return (round(random.gauss(0, 0.03), 3),
            round(random.gauss(0, 0.03), 3),
            round(1 + random.gauss(0, 0.03), 3))


def active_accel():
    """Wearer moving around (walking): more variation, still ~1 g mean."""
    return (round(random.gauss(0, 0.35), 3),
            round(random.gauss(0, 0.35), 3),
            round(1 + random.gauss(0, 0.35), 3))


def post(hr, accel, spo2=97, fall=False):
    payload = {
        "device_id": DEVICE_ID,
        "heart_rate": hr,
        "spo2": spo2,
        "accel_x": accel[0], "accel_y": accel[1], "accel_z": accel[2],
    }
    if fall:
        payload["fall"] = True
    try:
        r = requests.post(SERVER, json=payload, timeout=4)
        return r.json()
    except requests.RequestException as exc:
        print(f"  ! could not reach server: {exc}")
        return None


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------
def play_fall(t):
    """Free-fall dip, then a hard impact spike, then stillness on the floor."""
    print(">> Injecting FALL event")
    # Normal step or two
    post(normal_hr(t), active_accel())
    time.sleep(0.3)
    # Free-fall: acceleration drops toward 0 g
    for _ in range(3):
        post(normal_hr(t), (round(random.gauss(0, 0.05), 3),
                            round(random.gauss(0, 0.05), 3),
                            round(random.uniform(0.05, 0.3), 3)))
        time.sleep(0.1)
    # Impact: big spike well above 1 g
    post(normal_hr(t), (round(random.uniform(1.5, 2.5), 3),
                        round(random.uniform(1.5, 2.5), 3),
                        round(random.uniform(2.5, 3.5), 3)))
    time.sleep(0.2)
    # Lying still afterwards
    for _ in range(4):
        post(round(normal_hr(t) + 8, 1), still_accel())   # HR often rises after a fall
        time.sleep(0.4)


def play_tachycardia(t):
    """Heart rate climbs into the emergency-high band for a while."""
    print(">> Injecting TACHYCARDIA episode")
    for hr in range(95, 140, 6):
        post(round(hr + random.gauss(0, 2), 1), still_accel())
        time.sleep(0.5)
    for _ in range(4):
        post(round(135 + random.gauss(0, 3), 1), still_accel())
        time.sleep(0.5)


def play_bradycardia(t):
    """Heart rate drops into the emergency-low band."""
    print(">> Injecting BRADYCARDIA episode")
    for hr in range(70, 40, -5):
        post(round(hr + random.gauss(0, 1.5), 1), still_accel())
        time.sleep(0.5)
    for _ in range(4):
        post(round(42 + random.gauss(0, 1.5), 1), still_accel())
        time.sleep(0.5)


SCENARIOS = {"fall": play_fall, "tachy": play_tachycardia, "brady": play_bradycardia}


# ---------------------------------------------------------------------------
# History seeding (writes directly to the DB with past timestamps)
# ---------------------------------------------------------------------------
def seed_history(hours):
    """Backfill the DB so the trend chart has shape immediately."""
    print(f">> Seeding {hours}h of history...")
    db.init_db()
    now = datetime.utcnow()
    samples = hours * 12                       # one every ~5 minutes
    for i in range(samples):
        ts = now - timedelta(hours=hours) + timedelta(minutes=5 * i)
        t = i * 5
        # Daily rhythm: lower at night, higher midday
        hour_of_day = ts.hour + ts.minute / 60
        circadian = 8 * math.sin((hour_of_day - 4) / 24 * 2 * math.pi)
        hr = round(70 + circadian + random.gauss(0, 2.5), 1)
        ax, ay, az = still_accel()
        mag = math.sqrt(ax * ax + ay * ay + az * az)
        db.insert_reading(DEVICE_ID, hr, 97, ax, ay, az, mag,
                          timestamp=ts.isoformat())
    print(f"   seeded {samples} readings.")


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="ElderCare Guardian wearable simulator")
    ap.add_argument("--seed", type=int, metavar="HOURS",
                    help="backfill this many hours of history before streaming")
    ap.add_argument("--scenario", choices=SCENARIOS.keys(),
                    help="inject one scenario shortly after starting")
    ap.add_argument("--chaos", action="store_true",
                    help="occasionally inject random events while streaming")
    ap.add_argument("--interval", type=float, default=1.0,
                    help="seconds between normal readings (default 1.0)")
    args = ap.parse_args()

    if args.seed:
        seed_history(args.seed)

    print(f"Streaming live data to {SERVER}")
    print("Press Ctrl+C to stop.\n")

    t = 0
    moving = False
    scenario_fired = False
    try:
        while True:
            # Fire the requested scenario once, ~5s in.
            if args.scenario and not scenario_fired and t > 5:
                SCENARIOS[args.scenario](t)
                scenario_fired = True
                continue

            # Chaos mode: small chance of a random event each tick.
            if args.chaos and random.random() < 0.01:
                random.choice(list(SCENARIOS.values()))(t)
                continue

            # Occasionally switch between resting and walking.
            if random.random() < 0.05:
                moving = not moving

            hr = normal_hr(t)
            accel = active_accel() if moving else still_accel()
            result = post(hr, accel)

            state = (result or {}).get("motion", "?")
            flag = "  <-- FALL!" if (result or {}).get("fall_detected") else ""
            print(f"t={t:4d}s  HR={hr:5.1f}  motion={state:9}{flag}")

            t += 1
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nSimulator stopped.")


if __name__ == "__main__":
    main()
