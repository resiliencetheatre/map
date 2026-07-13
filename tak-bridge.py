#!/usr/bin/env python3
"""Receive CoT positions from a TAK server and post them to Situation."""

import argparse
import json
import math
import socket
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_MAX_EVENT_BYTES = 1024 * 1024
TAK_UNKNOWN_VALUE = 9999999.0
SIDC_BY_AFFILIATION = {
    "f": "SFGPUCI----K---",
    "h": "SHGPUCI----K---",
    "n": "SNGPUCI----K---",
    "u": "SUGPUCI----K---",
}


def log(message: str) -> None:
    print(message, flush=True)


def local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child(element: ET.Element, name: str) -> ET.Element | None:
    return next((item for item in element if local_name(item.tag) == name), None)


def descendant(element: ET.Element | None, name: str) -> ET.Element | None:
    if element is None:
        return None
    return next((item for item in element.iter() if local_name(item.tag) == name), None)


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def iso_z(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def finite_float(value: str | None, default: float = 0.0) -> float:
    try:
        number = float(value) if value is not None else default
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def cot_to_position(event: ET.Element, now: datetime | None = None) -> tuple[dict, datetime] | None:
    """Normalize one current CoT atom event for the existing position API."""
    cot_type = event.get("type", "")
    uid = event.get("uid", "").strip()
    event_time = parse_time(event.get("time"))
    stale_time = parse_time(event.get("stale"))
    point = child(event, "point")
    now = now or datetime.now(timezone.utc)

    # CoT atom types describe point entities. Other event families include chat,
    # routes, files and administrative traffic that this first bridge ignores.
    if not uid or len(uid) > 200 or len(cot_type) > 200 or not cot_type.startswith("a-") or point is None:
        return None
    if event_time is None or stale_time is None or stale_time <= now:
        return None

    latitude = finite_float(point.get("lat"), math.nan)
    longitude = finite_float(point.get("lon"), math.nan)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    detail = child(event, "detail")
    contact = descendant(detail, "contact")
    track = descendant(detail, "track")
    callsign = (contact.get("callsign", "").strip() if contact is not None else "") or uid
    heading = finite_float(track.get("course") if track is not None else None) % 360
    speed_mps = max(0.0, finite_float(track.get("speed") if track is not None else None))
    accuracy = max(0.0, finite_float(point.get("ce")))
    if accuracy >= TAK_UNKNOWN_VALUE:
        accuracy = 0.0
    parts = cot_type.split("-")
    affiliation = parts[1].lower() if len(parts) > 1 else "u"

    report = {
        "run_id": "tak",
        "device_id": uid,
        "timestamp": iso_z(event_time),
        "latitude": latitude,
        "longitude": longitude,
        "heading": heading,
        "speed": speed_mps * 3.6,
        "accuracy": accuracy,
        "sidc": SIDC_BY_AFFILIATION.get(affiliation, SIDC_BY_AFFILIATION["u"]),
        "designation": callsign[:100],
        "status_text": "TAK",
    }
    return report, event_time


def post_position(url: str, report: dict) -> None:
    body = json.dumps(report, separators=(",", ":")).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        if response.status != 201:
            raise RuntimeError(f"Situation returned HTTP {response.status}")


def receive_connection(
    tak_socket: socket.socket,
    api_url: str,
    latest_times: dict[str, datetime],
    max_event_bytes: int,
) -> None:
    parser = ET.XMLPullParser(events=("end",))
    parser.feed("<stream>")
    bytes_without_event = 0
    declaration_scan = b""

    while True:
        try:
            data = tak_socket.recv(65536)
        except socket.timeout:
            continue
        if not data:
            raise ConnectionError("TAK server closed the connection")
        bytes_without_event += len(data)
        if bytes_without_event > max_event_bytes:
            raise ValueError(f"CoT event exceeded {max_event_bytes} bytes")
        declaration_scan = (declaration_scan + data)[-65536:].upper()
        if b"<!DOCTYPE" in declaration_scan or b"<!ENTITY" in declaration_scan:
            raise ValueError("XML declarations are not accepted in CoT events")

        parser.feed(data)
        for _event_kind, element in parser.read_events():
            if local_name(element.tag) != "event":
                continue
            bytes_without_event = 0
            normalized = cot_to_position(element)
            if normalized is not None:
                report, event_time = normalized
                previous = latest_times.get(report["device_id"])
                if previous is None or event_time > previous:
                    try:
                        post_position(api_url, report)
                    except (HTTPError, URLError, RuntimeError) as error:
                        log(f"Cannot post {report['device_id']}: {error}")
                    else:
                        latest_times[report["device_id"]] = event_time
                        log(f"Updated {report['designation']} ({report['device_id']})")
            element.clear()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward position CoT from taky-ng to the Situation position API"
    )
    parser.add_argument("--host", default="127.0.0.1", help="TAK server host")
    parser.add_argument("--port", type=int, default=8087, help="plain TAK TCP port")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8080/api/positions",
        help="Situation position API URL",
    )
    parser.add_argument(
        "--reconnect-delay", type=float, default=3.0,
        help="seconds before reconnecting (default: 3)",
    )
    parser.add_argument(
        "--max-event-bytes", type=int, default=DEFAULT_MAX_EVENT_BYTES,
        help="maximum CoT XML bytes between events (default: 1048576)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not 1 <= args.port <= 65535:
        raise SystemExit("--port must be between 1 and 65535")
    if args.reconnect_delay < 0 or args.max_event_bytes < 1024:
        raise SystemExit("--reconnect-delay cannot be negative; --max-event-bytes must be at least 1024")

    latest_times: dict[str, datetime] = {}
    log(f"Forwarding TAK {args.host}:{args.port} to {args.url}")
    try:
        while True:
            try:
                with socket.create_connection((args.host, args.port), timeout=10) as tak_socket:
                    tak_socket.settimeout(1)
                    log(f"Connected to TAK server at {args.host}:{args.port}")
                    receive_connection(tak_socket, args.url, latest_times, args.max_event_bytes)
            except (ConnectionError, OSError, ET.ParseError, ValueError) as error:
                log(f"TAK connection lost: {error}; retrying in {args.reconnect_delay:g}s")
                time.sleep(args.reconnect_delay)
    except KeyboardInterrupt:
        log("TAK bridge stopped")


if __name__ == "__main__":
    main()
