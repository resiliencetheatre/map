import importlib.util
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tak-bridge.py"
SPEC = importlib.util.spec_from_file_location("tak_bridge", MODULE_PATH)
tak_bridge = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(tak_bridge)


class CotNormalizationTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)

    def event(self, **overrides):
        values = {
            "uid": "ANDROID-deadbeef",
            "type": "a-f-G-U-C",
            "time": "2026-07-14T12:00:01Z",
            "stale": "2026-07-14T12:02:01Z",
        }
        values.update(overrides)
        attributes = " ".join(f'{key}="{value}"' for key, value in values.items())
        return ET.fromstring(
            f'<event {attributes}><point lat="49.61" lon="6.13" ce="4.5"/>'
            '<detail><contact callsign="ALPHA 1"/><track course="361" speed="2.5"/></detail>'
            '</event>'
        )

    def test_normalizes_atom_position_for_position_api(self):
        report, event_time = tak_bridge.cot_to_position(self.event(), self.now)
        self.assertEqual(report["device_id"], "ANDROID-deadbeef")
        self.assertEqual(report["designation"], "ALPHA 1")
        self.assertEqual(report["sidc"], "SFGPUCI----K---")
        self.assertEqual(report["heading"], 1.0)
        self.assertEqual(report["speed"], 9.0)
        self.assertEqual(report["accuracy"], 4.5)
        self.assertEqual(event_time, datetime(2026, 7, 14, 12, 0, 1, tzinfo=timezone.utc))

    def test_rejects_expired_event(self):
        event = self.event(stale="2026-07-14T11:59:59Z")
        self.assertIsNone(tak_bridge.cot_to_position(event, self.now))

    def test_rejects_non_atom_event(self):
        event = self.event(type="b-t-f")
        self.assertIsNone(tak_bridge.cot_to_position(event, self.now))

    def test_rejects_invalid_coordinates(self):
        event = self.event()
        event.find("point").set("lat", "91")
        self.assertIsNone(tak_bridge.cot_to_position(event, self.now))

    def test_rejects_oversized_identity(self):
        event = self.event(uid="x" * 201)
        self.assertIsNone(tak_bridge.cot_to_position(event, self.now))

    def test_normalizes_tak_unknown_accuracy(self):
        event = self.event()
        event.find("point").set("ce", "9999999.0")
        report, _event_time = tak_bridge.cot_to_position(event, self.now)
        self.assertEqual(report["accuracy"], 0.0)

    def test_reports_reason_for_non_position_event(self):
        normalized, reason = tak_bridge.normalize_cot_event(
            self.event(type="b-t-f"), self.now
        )
        self.assertIsNone(normalized)
        self.assertEqual(reason, "non-atom event type")

    def test_observation_lists_nested_detail_types(self):
        observation = tak_bridge.event_observation(
            self.event(), "forwarded", "position event"
        )
        self.assertEqual(observation["type"], "a-f-G-U-C")
        self.assertTrue(observation["has_point"])
        self.assertEqual(observation["detail_types"], ["contact", "track"])


if __name__ == "__main__":
    unittest.main()
