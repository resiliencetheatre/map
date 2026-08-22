#!/usr/bin/env python3
"""Read a local NMEA GPS and forward fixes to the Situation API."""

import argparse
import json
import math
import os
import select
import termios
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


# Neutral, present, ground, unspecified unit. Operators may override this.
GPS_SIDC = "SNGPU------K---"
BAUD_RATES = {
    4800: termios.B4800,
    9600: termios.B9600,
    19200: termios.B19200,
    38400: termios.B38400,
    57600: termios.B57600,
    115200: termios.B115200,
}


def nmea_coordinate(value: str, hemisphere: str) -> float:
    """Convert an NMEA ddmm.mmmm coordinate to signed decimal degrees."""
    if not value or hemisphere not in {"N", "S", "E", "W"}:
        raise ValueError("invalid NMEA coordinate")
    raw = float(value)
    degrees = int(raw // 100)
    coordinate = degrees + (raw - degrees * 100) / 60
    if hemisphere in {"S", "W"}:
        coordinate = -coordinate
    limit = 90 if hemisphere in {"N", "S"} else 180
    if not math.isfinite(coordinate) or not -limit <= coordinate <= limit:
        raise ValueError("NMEA coordinate is out of range")
    return coordinate


def nmea_fields(line: str) -> list[str] | None:
    """Validate an NMEA checksum and return fields without '$' or checksum."""
    sentence = line.strip()
    if not sentence.startswith("$") or "*" not in sentence:
        return None
    payload, supplied = sentence[1:].rsplit("*", 1)
    if len(supplied) < 2:
        return None
    checksum = 0
    for character in payload:
        checksum ^= ord(character)
    try:
        expected = int(supplied[:2], 16)
    except ValueError:
        return None
    return payload.split(",") if checksum == expected else None


def utc_timestamp(time_text: str, date_text: str) -> str:
    value = datetime.strptime(date_text + time_text.split(".", 1)[0], "%d%m%y%H%M%S")
    return value.replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


class NmeaGps:
    """Small stateful NMEA parser; feed it complete lines with ``parse``."""

    def __init__(
        self,
        device_id: str = "local-gps",
        designation: str = "Local GPS",
        sidc: str = GPS_SIDC,
    ):
        self.device_id = device_id
        self.designation = designation
        self.sidc = sidc
        self.altitude = None
        self.satellites = None
        self.hdop = None

    def parse(self, line: str) -> dict | None:
        fields = nmea_fields(line)
        if not fields:
            return None
        sentence = fields[0][-3:]
        try:
            if sentence == "GGA":
                if len(fields) >= 10 and int(fields[6] or 0) > 0:
                    self.satellites = int(fields[7]) if fields[7] else None
                    self.hdop = float(fields[8]) if fields[8] else None
                    self.altitude = float(fields[9]) if fields[9] else None
                return None
            if sentence != "RMC" or len(fields) < 10 or fields[2] != "A":
                return None
            latitude = nmea_coordinate(fields[3], fields[4])
            longitude = nmea_coordinate(fields[5], fields[6])
            speed = max(0.0, float(fields[7] or 0) * 1.852)  # knots to km/h
            heading = float(fields[8] or 0) % 360
            timestamp = utc_timestamp(fields[1], fields[9])
        except (ValueError, OverflowError):
            return None

        details = ["u-blox NEO-M9N"]
        if self.satellites is not None:
            details.append(f"{self.satellites} satellites")
        if self.hdop is not None and math.isfinite(self.hdop):
            details.append(f"HDOP {self.hdop:g}")
        if self.altitude is not None and math.isfinite(self.altitude):
            details.append(f"alt {self.altitude:g} m")
        return {
            "run_id": "gps",
            "device_id": self.device_id,
            "timestamp": timestamp,
            "latitude": latitude,
            "longitude": longitude,
            "heading": heading,
            "speed": speed,
            "accuracy": 0.0,
            "sidc": self.sidc,
            "designation": self.designation,
            "status_text": " · ".join(details),
        }


def open_serial(path: str, baud: int):
    """Open a Linux serial device as a line-buffered text stream."""
    descriptor = os.open(path, os.O_RDONLY | os.O_NOCTTY)
    try:
        attributes = termios.tcgetattr(descriptor)
        attributes[0] = 0
        attributes[1] = 0
        attributes[2] = termios.CS8 | termios.CREAD | termios.CLOCAL
        attributes[3] = 0
        attributes[4] = BAUD_RATES[baud]
        attributes[5] = BAUD_RATES[baud]
        attributes[6][termios.VMIN] = 1
        attributes[6][termios.VTIME] = 0
        termios.tcsetattr(descriptor, termios.TCSANOW, attributes)
        return os.fdopen(descriptor, "r", encoding="ascii", errors="replace", buffering=1)
    except Exception:
        os.close(descriptor)
        raise


def post_position(url: str, report: dict) -> None:
    body = json.dumps(report, separators=(",", ":")).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        if response.status != 201:
            raise RuntimeError(f"Situation returned HTTP {response.status}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Forward a local NMEA GPS to Situation")
    parser.add_argument("--port", default="/dev/ttyUSB1", help="serial device")
    parser.add_argument("--baud", type=int, choices=BAUD_RATES, default=38400)
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/positions")
    parser.add_argument("--device-id", default="local-gps")
    parser.add_argument("--designation", default="Local GPS")
    parser.add_argument(
        "--sidc", default=GPS_SIDC,
        help=f"map symbol SIDC (default: {GPS_SIDC}, neutral generic unit)",
    )
    parser.add_argument("--reconnect-delay", type=float, default=3.0)
    parser.add_argument(
        "--debug", action="store_true",
        help="show received NMEA sentences and serial-port liveness",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.reconnect_delay < 0:
        raise SystemExit("--reconnect-delay cannot be negative")
    args.sidc = args.sidc.strip()
    if not args.sidc or len(args.sidc) > 50:
        raise SystemExit("--sidc must contain between 1 and 50 characters")
    gps = NmeaGps(args.device_id, args.designation, args.sidc)
    print(f"Reading {args.port} at {args.baud} baud; posting to {args.url}", flush=True)
    try:
        while True:
            try:
                with open_serial(args.port, args.baud) as serial:
                    if args.debug:
                        print(f"DEBUG: opened {args.port}; waiting for GPS data", flush=True)
                    received = 0
                    while True:
                        readable, _, _ = select.select([serial], [], [], 5.0)
                        if not readable:
                            if args.debug:
                                print(
                                    f"DEBUG: no serial data for 5 seconds "
                                    f"({received} lines received since open)",
                                    flush=True,
                                )
                            continue
                        line = serial.readline()
                        if line == "":
                            raise OSError("serial device returned end-of-file")
                        received += 1
                        if args.debug:
                            printable = line.rstrip("\r\n")
                            fields = nmea_fields(printable)
                            if fields:
                                detail = f"valid {fields[0]}"
                                if fields[0].endswith("RMC"):
                                    detail += " fix" if len(fields) > 2 and fields[2] == "A" else " no-fix"
                            else:
                                detail = "invalid checksum or non-NMEA"
                            print(f"DEBUG RX [{detail}]: {printable[:200]}", flush=True)
                        report = gps.parse(line)
                        if report is None:
                            continue
                        try:
                            post_position(args.url, report)
                        except (HTTPError, URLError, OSError, RuntimeError) as error:
                            print(f"Cannot post GPS fix: {error}", flush=True)
                        else:
                            print(
                                f"GPS fix {report['latitude']:.6f}, {report['longitude']:.6f}",
                                flush=True,
                            )
            except (OSError, termios.error) as error:
                print(f"Cannot read {args.port}: {error}; retrying", flush=True)
            time.sleep(args.reconnect_delay)
    except KeyboardInterrupt:
        print("GPS adapter stopped", flush=True)


if __name__ == "__main__":
    main()
