#!/usr/bin/env python3
"""Forward Meshtastic node locations and radio metadata to Situation."""

import argparse
import json
import math
import threading
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


MESHTASTIC_SIDC = "SFGPUCI----K---"


def iso_z(timestamp: float | int | None = None) -> str:
    numeric = finite_number(timestamp, 0.0)
    try:
        value = datetime.fromtimestamp(numeric, timezone.utc) if numeric > 0 else datetime.now(timezone.utc)
    except (OverflowError, OSError, ValueError):
        value = datetime.now(timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


def finite_number(value: object, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def coordinate(position: dict, name: str) -> float | None:
    value = position.get(name)
    if value is None:
        value = position.get(f"{name}I")
        if value is not None:
            value = finite_number(value, math.nan) / 10_000_000
    number = finite_number(value, math.nan)
    return number if math.isfinite(number) else None


def status_text(node: dict) -> str:
    """Build a compact operator-facing summary from the node database."""
    user = node.get("user") or {}
    metrics = node.get("deviceMetrics") or {}
    position = node.get("position") or {}
    last_packet = node.get("lastReceived") or {}
    parts = ["Meshtastic"]
    fields = (
        (metrics.get("batteryLevel"), lambda value: f"battery {value:g}%"),
        (metrics.get("voltage"), lambda value: f"{value:g} V"),
        (user.get("hwModel"), lambda value: f"{value}"),
        (node.get("snr"), lambda value: f"SNR {value:g} dB"),
        (node.get("rssi", last_packet.get("rxRssi")), lambda value: f"RSSI {value:g} dBm"),
        (node.get("hopsAway"), lambda value: f"{value:g} hop{'s' if value != 1 else ''}"),
        (position.get("altitude"), lambda value: f"alt {value:g} m"),
        (position.get("satsInView"), lambda value: f"{value:g} satellites"),
        (position.get("PDOP", position.get("pdop")), lambda value: f"PDOP {value:g}"),
        (metrics.get("channelUtilization"), lambda value: f"channel {value:g}%"),
        (metrics.get("airUtilTx"), lambda value: f"air TX {value:g}%"),
    )
    for raw, formatter in fields:
        if raw is None or isinstance(raw, bool):
            continue
        if isinstance(raw, (int, float)) and not math.isfinite(float(raw)):
            continue
        try:
            parts.append(formatter(raw))
        except (TypeError, ValueError):
            continue
    return " · ".join(parts)[:500]


def node_to_position(node: object, now: float | None = None) -> dict | None:
    """Normalize one Meshtastic node-database entry for Situation's API."""
    if not isinstance(node, dict):
        return None
    position = node.get("position")
    if not isinstance(position, dict):
        return None
    latitude = coordinate(position, "latitude")
    longitude = coordinate(position, "longitude")
    if latitude is None or longitude is None:
        return None
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None

    user = node.get("user") if isinstance(node.get("user"), dict) else {}
    node_num = node.get("num")
    fallback_id = f"!{int(node_num) & 0xffffffff:08x}" if isinstance(node_num, int) else ""
    node_id = str(user.get("id") or fallback_id).strip()
    if not node_id:
        return None
    designation = str(user.get("longName") or user.get("shortName") or node_id).strip()[:100]
    source_time = position.get("time") or node.get("lastHeard") or now
    heading = finite_number(position.get("groundTrack", position.get("heading"))) % 360
    # Meshtastic groundSpeed is metres/second; Situation stores kilometres/hour.
    speed = max(0.0, finite_number(position.get("groundSpeed")) * 3.6)

    report = {
        "run_id": "meshtastic",
        "device_id": f"meshtastic:{node_id}",
        "timestamp": iso_z(source_time),
        "latitude": latitude,
        "longitude": longitude,
        "heading": heading,
        "speed": speed,
        "accuracy": 0.0,
        "sidc": MESHTASTIC_SIDC,
        "designation": designation,
        "status_text": status_text(node),
    }
    last_heard = finite_number(node.get("lastHeard"), 0.0)
    if last_heard > 0:
        report["activity_at"] = iso_z(last_heard)
    return report


def post_position(url: str, report: dict) -> None:
    body = json.dumps(report, separators=(",", ":")).encode()
    request = Request(url, data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        if response.status != 201:
            raise RuntimeError(f"Situation returned HTTP {response.status}")


class MeshtasticAdapter:
    def __init__(self, url: str, interval: float):
        self.url = url
        self.interval = interval
        self.interface = None
        self.changed = threading.Event()
        self.disconnected = threading.Event()
        self.last_reports: dict[str, str] = {}

    def on_connection(self, interface, **_kwargs) -> None:
        self.interface = interface
        self.disconnected.clear()
        self.changed.set()
        print("Meshtastic node database downloaded", flush=True)

    def on_disconnect(self, interface=None, **_kwargs) -> None:
        self.disconnected.set()
        self.changed.set()
        print("Meshtastic radio disconnected", flush=True)

    def on_node_updated(self, node=None, interface=None, **_kwargs) -> None:
        # Current Meshtastic releases publish both values.  Naming interface
        # explicitly is important because PyPubSub derives the topic argument
        # schema from the first subscribed listener's signature.
        if interface is not None:
            self.interface = interface
        self.changed.set()

    def sync(self) -> None:
        interface = self.interface
        nodes = getattr(interface, "nodesByNum", {}) if interface is not None else {}
        for node in list(nodes.values()):
            report = node_to_position(node)
            if report is None:
                continue
            fingerprint = json.dumps(report, sort_keys=True, separators=(",", ":"))
            device_id = report["device_id"]
            if self.last_reports.get(device_id) == fingerprint:
                continue
            try:
                post_position(self.url, report)
            except (HTTPError, URLError, OSError, RuntimeError) as error:
                print(f"Cannot post {device_id}: {error}", flush=True)
            else:
                self.last_reports[device_id] = fingerprint
                print(f"Updated {report['designation']} ({device_id})", flush=True)

    def run_connected(self, interface) -> None:
        self.interface = interface
        self.changed.set()
        while not self.disconnected.is_set():
            self.changed.wait(self.interval)
            self.changed.clear()
            self.sync()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Forward Meshtastic node locations to the Situation position API"
    )
    parser.add_argument("--port", help="serial device, for example /dev/ttyACM0 (default: auto-detect)")
    parser.add_argument(
        "--url", default="http://127.0.0.1:8080/api/positions",
        help="Situation position API URL",
    )
    parser.add_argument("--interval", type=float, default=30.0, help="full node scan interval")
    parser.add_argument("--reconnect-delay", type=float, default=3.0, help="delay after disconnect")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interval <= 0 or args.reconnect_delay < 0:
        raise SystemExit("--interval must be positive and --reconnect-delay cannot be negative")
    try:
        import meshtastic.serial_interface
        from pubsub import pub
    except ImportError as error:
        raise SystemExit("Install the radio dependency with: python3 -m pip install meshtastic") from error

    adapter = MeshtasticAdapter(args.url, args.interval)
    pub.subscribe(adapter.on_connection, "meshtastic.connection.established")
    pub.subscribe(adapter.on_disconnect, "meshtastic.connection.lost")
    pub.subscribe(adapter.on_node_updated, "meshtastic.node.updated")
    print(f"Forwarding Meshtastic positions to {args.url}", flush=True)
    try:
        while True:
            adapter.disconnected.clear()
            try:
                interface = meshtastic.serial_interface.SerialInterface(devPath=args.port)
                adapter.run_connected(interface)
            except Exception as error:  # Library connection/protobuf errors vary by release.
                print(f"Meshtastic connection failed: {error}", flush=True)
            finally:
                if "interface" in locals():
                    try:
                        interface.close()
                    except Exception as error:
                        print(f"Cannot close Meshtastic interface cleanly: {error}", flush=True)
                    del interface
            time.sleep(args.reconnect_delay)
    except KeyboardInterrupt:
        print("Meshtastic adapter stopped", flush=True)


if __name__ == "__main__":
    main()
