import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "python-front.py"
SPEC = importlib.util.spec_from_file_location("python_front", MODULE_PATH)
front = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(front)


class ActivityTimestampTests(unittest.TestCase):
    def report(self, **overrides):
        report = {
            "run_id": "test",
            "device_id": "node-1",
            "timestamp": "2026-08-08T10:00:00Z",
            "latitude": 49.6,
            "longitude": 6.1,
            "heading": 0,
            "speed": 0,
            "accuracy": 0,
            "sidc": "SFGPUCI----K---",
            "designation": "Node 1",
        }
        report.update(overrides)
        return report

    def test_activity_at_is_optional(self):
        self.assertIsNone(front.validate_position(self.report())["activity_at"])

    def test_normalizes_activity_at_to_utc(self):
        result = front.validate_position(
            self.report(activity_at="2026-08-08T12:00:00+02:00")
        )
        self.assertEqual(result["activity_at"], "2026-08-08T10:00:00Z")

    def test_rejects_activity_at_without_timezone(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            front.validate_position(self.report(activity_at="2026-08-08T10:00:00"))

    def test_rejects_oversized_activity_at(self):
        with self.assertRaisesRegex(ValueError, "at most 100"):
            front.validate_position(self.report(activity_at="2" * 101))

    def test_database_migration_adds_activity_at(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "situation.db"
            with sqlite3.connect(database) as connection:
                connection.execute("""
                    CREATE TABLE positions (
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
                        designation TEXT NOT NULL,
                        status_text TEXT NOT NULL DEFAULT ''
                    )
                """)
            front.init_database(database)
            with sqlite3.connect(database) as connection:
                columns = {row[1] for row in connection.execute("PRAGMA table_info(positions)")}
            self.assertIn("activity_at", columns)


class ViewpointTests(unittest.TestCase):
    def test_playback_validation(self):
        frames = [[0, 6, 49, 90], [10, 6.01, 49, 90]]
        result = front.validate_viewpoint(self.viewpoint(playback=frames))
        self.assertEqual(result["playback"], frames)
        for invalid in ([], frames[:1], [frames[0], frames[0]], [[1, 6, 49, 90], frames[1]],
                        [[0, 6, 49, 90], [10, float("nan"), 49, 90]]):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                front.validate_viewpoint(self.viewpoint(playback=invalid))

    def test_centre_only_and_partial_camera(self):
        pan = front.validate_viewpoint({"longitude": 6, "latitude": 49, "smoothing": 0.5})
        self.assertEqual(set(pan), {"longitude", "latitude", "smoothing", "duration"})
        for field in ("tilt", "altitude", "bearing"):
            with self.subTest(field=field), self.assertRaises(ValueError):
                front.validate_viewpoint({"longitude": 6, "latitude": 49, field: 60})

    def viewpoint(self, **overrides):
        return {"longitude": 6.1, "latitude": 49.6, "altitude": 1000,
                "tilt": 60, "bearing": 90, "duration": 0.1, **overrides}

    def test_validation(self):
        self.assertEqual(front.validate_viewpoint(self.viewpoint(bearing=-90))["bearing"], 270)
        for field, value in (("latitude", 86), ("longitude", 181), ("altitude", 0),
                             ("tilt", 90), ("bearing", float("nan")),
                             ("duration", -1), ("altitude", True), ("tilt", "60"),
                             ("smoothing", -1), ("smoothing", float("nan")),
                             ("smoothing", True), ("smoothing", 6)):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                front.validate_viewpoint(self.viewpoint(**{field: value}))

    def test_http_handler_roundtrip_and_rejected_update(self):
        # Exercise real HTTP parsing/serialization without opening a socket.
        handler = front.make_handler(Path("web"), Path("maps"), Path("maplibre-gl-js"), Path("unused.db"))

        class Connection:
            def __init__(self, request):
                self.request = request
                self.response = b""

            def makefile(self, *args):
                return io.BytesIO(self.request)

            def sendall(self, data):
                self.response += data

        def request(method, data=None, query=""):
            body = json.dumps(data).encode() if data is not None else b""
            connection = Connection(
                f"{method} /api/viewpoint{query} HTTP/1.0\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
            handler(connection, ("127.0.0.1", 1), None)
            headers, payload = connection.response.split(b"\r\n\r\n", 1)
            return int(headers.split()[1]), json.loads(payload)

        self.assertEqual(request("GET"), (200, {"viewpoint": None}))
        status, saved = request("POST", self.viewpoint())
        self.assertEqual(status, 200)
        self.assertTrue(saved["viewpoint"]["id"])
        self.assertEqual(request("GET"), (200, saved))
        self.assertEqual(request("POST", self.viewpoint(tilt=100))[0], 400)
        self.assertEqual(request("GET"), (200, saved))
        self.assertNotEqual(request("POST", self.viewpoint())[1]["viewpoint"]["id"], saved["viewpoint"]["id"])
        from concurrent.futures import ThreadPoolExecutor
        current = request("GET")[1]["viewpoint"]
        with ThreadPoolExecutor() as pool:
            waiting = pool.submit(request, "GET", None, "?after=" + current["id"])
            changed = request("POST", self.viewpoint(playback=[[0, 6, 49, 90], [10, 7, 49, 90]]))[1]
            status, update = waiting.result(timeout=2)
        self.assertEqual(status, 200)
        self.assertEqual(update["viewpoint"], changed["viewpoint"])
        self.assertGreaterEqual(update["elapsed"], 0)


if __name__ == "__main__":
    unittest.main()
