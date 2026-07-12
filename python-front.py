#!/usr/bin/env python3
"""Small, dependency-free server for the Situation frontend."""

import argparse
import json
import mimetypes
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit


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


def make_handler(web_dir: Path, map_dir: Path, maplibre_dir: Path):
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

    return SituationHandler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Serve the Situation web application")
    parser.add_argument("--listen", default="127.0.0.1", help="address to bind")
    parser.add_argument("--port", type=int, default=8080, help="TCP port")
    parser.add_argument("--web-dir", default="./web", help="frontend directory")
    parser.add_argument("--map-dir", default="./maps", help="map asset directory")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    web_dir = Path(args.web_dir).resolve()
    map_dir = Path(args.map_dir).resolve()
    maplibre_dir = (Path(__file__).resolve().parent / "maplibre-gl-js").resolve()
    server = ThreadingHTTPServer(
        (args.listen, args.port), make_handler(web_dir, map_dir, maplibre_dir)
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
