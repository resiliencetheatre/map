#!/usr/bin/env python3
"""Post three moving demonstration units to the Situation position API."""

import argparse
import json
import math
import time
import uuid
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen


UNITS = (
    ("civil-protection", "E-O-B-----", "Civil Protection Team", 6.13, 49.61, 0.045, 0.025, 0.0),
    ("fire-rescue", "E-O-C-----", "Fire and Rescue Service", 6.32, 49.68, 0.055, 0.018, 2.1),
    ("medical-response", "E-O-A-----", "Emergency Medical Service", 5.98, 49.52, 0.035, 0.030, 4.2),
)


def position(unit: tuple, tick: int, run_id: str) -> dict:
    device_id, sidc, designation, lon, lat, radius_x, radius_y, phase = unit
    angle = tick * 0.08 + phase
    longitude = lon + math.cos(angle) * radius_x
    latitude = lat + math.sin(angle) * radius_y
    heading = (90 - math.degrees(angle)) % 360
    return {
        "run_id": run_id,
        "device_id": device_id,
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "latitude": round(latitude, 6),
        "longitude": round(longitude, 6),
        "heading": round(heading, 1),
        "speed": 8.0,
        "accuracy": 5.0,
        "sidc": sidc,
        "designation": designation,
        "status_text": "simulation",
    }


def post(url: str, report: dict) -> None:
    body = json.dumps(report).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        if response.status != 201:
            raise RuntimeError(f"server returned HTTP {response.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate three moving map units")
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/positions")
    parser.add_argument(
        "--interval", type=float, default=1.0,
        help="seconds per update, minimum 0.1 (default: 1.0)",
    )
    parser.add_argument("--steps", type=int, default=0, help="updates; 0 runs forever")
    parser.add_argument("--run-id", help="track session ID; defaults to a UUID")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval < 0.1 or args.steps < 0:
        raise SystemExit("--interval must be at least 0.1 and --steps cannot be negative")
    run_id = args.run_id or str(uuid.uuid4())
    print(f"Simulation run {run_id}; posting to {args.url}")
    tick = 0
    next_update = time.monotonic()
    try:
        while args.steps == 0 or tick < args.steps:
            for unit in UNITS:
                report = position(unit, tick, run_id)
                try:
                    post(args.url, report)
                except (URLError, RuntimeError) as error:
                    print(f"{report['device_id']}: {error}")
            tick += 1
            next_update += args.interval
            time.sleep(max(0, next_update - time.monotonic()))
    except KeyboardInterrupt:
        pass
    print(f"Simulation stopped after {tick} updates")


if __name__ == "__main__":
    main()
