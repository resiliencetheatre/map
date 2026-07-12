#!/usr/bin/env python3
"""Small, dependency-free server for the Situation frontend."""

import argparse
import json
import math
import mimetypes
import re
import sqlite3
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


POSITION_FIELDS = ("run_id", "device_id", "timestamp", "latitude", "longitude",
                   "heading", "speed", "accuracy", "sidc", "designation")


def init_database(database: Path) -> None:
    """Create the append-only position store when it does not yet exist."""
    with sqlite3.connect(database) as connection:
        connection.executescript("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                device_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                received_at TEXT NOT NULL,
                latitude REAL NOT NULL,
                longitude REAL NOT NULL,
                heading REAL,
                speed REAL,
                accuracy REAL,
                sidc TEXT NOT NULL,
                designation TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS positions_run_time
                ON positions (run_id, timestamp);
            CREATE INDEX IF NOT EXISTS positions_device_id
                ON positions (device_id, id);
        """)


def validate_position(data: object) -> dict:
    """Return a normalized position report or raise ValueError."""
    if not isinstance(data, dict):
        raise ValueError("JSON body must be an object")
    missing = [field for field in POSITION_FIELDS if field not in data]
    if missing:
        raise ValueError(f"missing fields: {', '.join(missing)}")

    position = {field: data[field] for field in POSITION_FIELDS}
    for field in ("run_id", "device_id", "timestamp", "sidc", "designation"):
        if not isinstance(position[field], str) or not position[field].strip():
            raise ValueError(f"{field} must be a non-empty string")
    for field in ("latitude", "longitude", "heading", "speed", "accuracy"):
        try:
            position[field] = float(position[field])
        except (TypeError, ValueError) as error:
            raise ValueError(f"{field} must be numeric") from error
        if not math.isfinite(position[field]):
            raise ValueError(f"{field} must be finite")
    if not -90 <= position["latitude"] <= 90:
        raise ValueError("latitude is out of range")
    if not -180 <= position["longitude"] <= 180:
        raise ValueError("longitude is out of range")
    position["heading"] %= 360
    if position["speed"] < 0 or position["accuracy"] < 0:
        raise ValueError("speed and accuracy cannot be negative")
    return position


def safe_file(root: Path, requested: str, *, allow_symlink: bool = False) -> Path | None:
    """Resolve a URL path below root, rejecting traversal and directories."""
    try:
        relative = Path(unquote(requested).lstrip("/"))
        if ".." in relative.parts:
            return None
        candidate = root / relative
        if not allow_symlink:
            candidate.resolve().relative_to(root)
    except (ValueError, OSError):
        return None
    return candidate if candidate.is_file() else None


def make_handler(web_dir: Path, map_dir: Path, maplibre_dir: Path, database: Path):
    class SituationHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            path = urlsplit(self.path).path

            if path == "/health":
                self._send_bytes(b"OK", "text/plain; charset=utf-8")
                return

            if path == "/api/status":
                payload = json.dumps({"status": "ok", "service": "Situation"}).encode()
                self._send_bytes(payload, "application/json; charset=utf-8")
                return

            if path == "/api/positions":
                with sqlite3.connect(database) as connection:
                    connection.row_factory = sqlite3.Row
                    rows = connection.execute("""
                        SELECT * FROM positions
                        WHERE id IN (SELECT MAX(id) FROM positions GROUP BY device_id)
                        ORDER BY device_id
                    """).fetchall()
                self._send_json({"positions": [dict(row) for row in rows]})
                return

            if path == "/api/tracks":
                with sqlite3.connect(database) as connection:
                    connection.row_factory = sqlite3.Row
                    rows = connection.execute("""
                        SELECT run_id, MIN(timestamp) AS started_at,
                               MAX(timestamp) AS ended_at, COUNT(*) AS points,
                               COUNT(DISTINCT device_id) AS devices
                        FROM positions GROUP BY run_id ORDER BY ended_at DESC
                    """).fetchall()
                self._send_json({"tracks": [dict(row) for row in rows]})
                return

            track_match = re.fullmatch(r"/api/tracks/([^/]+)", path)
            if track_match:
                run_id = unquote(track_match.group(1))
                with sqlite3.connect(database) as connection:
                    connection.row_factory = sqlite3.Row
                    rows = connection.execute(
                        "SELECT * FROM positions WHERE run_id = ? ORDER BY timestamp, id",
                        (run_id,),
                    ).fetchall()
                self._send_json({"run_id": run_id, "positions": [dict(row) for row in rows]})
                return

            # Map assets have their own URL namespace; everything else is web UI.
            if path == "/maps" or path.startswith("/maps/"):
                relative = path.removeprefix("/maps/") if path != "/maps" else ""
                # Map archives may be explicit operator-managed symlinks.
                file_path = safe_file(map_dir, relative, allow_symlink=True)
            elif path.startswith("/maplibre/"):
                file_path = safe_file(maplibre_dir, path.removeprefix("/maplibre/"))
            else:
                relative = "index.html" if path == "/" else path
                file_path = safe_file(web_dir, relative)

            if file_path is None:
                self.send_error(404, "Not found")
                return

            self._send_file(file_path)

        def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
            if urlsplit(self.path).path != "/api/positions":
                self.send_error(404, "Not found")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 64 * 1024:
                    raise ValueError("request body must be between 1 byte and 64 KiB")
                data = json.loads(self.rfile.read(length))
                position = validate_position(data)
            except (ValueError, json.JSONDecodeError) as error:
                self._send_json({"error": str(error)}, status=400)
                return

            received_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            values = [position[field] for field in POSITION_FIELDS]
            with sqlite3.connect(database) as connection:
                cursor = connection.execute("""
                    INSERT INTO positions (
                        run_id, device_id, timestamp, latitude, longitude,
                        heading, speed, accuracy, sidc, designation, received_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (*values, received_at))
                row_id = cursor.lastrowid
            self._send_json({"stored": True, "id": row_id}, status=201)

        def _send_file(self, file_path: Path) -> None:
            """Stream a whole file or one HTTP byte range without buffering it."""
            size = file_path.stat().st_size
            start, end = 0, size - 1
            status = 200
            range_header = self.headers.get("Range")
            if range_header:
                match = re.fullmatch(r"bytes=(\d+)-(\d*)", range_header)
                if not match:
                    self.send_error(416, "Invalid range")
                    return
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else size - 1
                if start >= size or end < start:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{size}")
                    self.end_headers()
                    return
                end = min(end, size - 1)
                status = 206

            length = end - start + 1
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("X-Content-Type-Options", "nosniff")
            if status == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()

            with file_path.open("rb") as source:
                source.seek(start)
                remaining = length
                try:
                    while remaining:
                        chunk = source.read(min(64 * 1024, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    # Map renderers routinely cancel obsolete in-flight tiles.
                    # A closed client socket is expected, not a server failure.
                    return

        def _send_bytes(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, value: object, status: int = 200) -> None:
            body = json.dumps(value, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return SituationHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Situation web application")
    parser.add_argument("--listen", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", type=int, default=8080, help="TCP port")
    parser.add_argument("--web-dir", default="./web", help="frontend directory")
    parser.add_argument("--map-dir", default="./maps", help="map asset directory")
    parser.add_argument("--database", default="./situation.db", help="SQLite database")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    web_dir = Path(args.web_dir).resolve()
    map_dir = Path(args.map_dir).resolve()
    database = Path(args.database).resolve()
    database.parent.mkdir(parents=True, exist_ok=True)
    init_database(database)
    maplibre_dir = (Path(__file__).resolve().parent / "maplibre-gl-js").resolve()
    server = ThreadingHTTPServer(
        (args.listen, args.port), make_handler(web_dir, map_dir, maplibre_dir, database)
    )
    print(f"Situation listening on http://{args.listen}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
