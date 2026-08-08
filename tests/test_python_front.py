import importlib.util
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


if __name__ == "__main__":
    unittest.main()
