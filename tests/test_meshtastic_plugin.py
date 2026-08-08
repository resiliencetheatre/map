import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "meshtastic-plugin.py"
SPEC = importlib.util.spec_from_file_location("meshtastic_plugin", MODULE_PATH)
plugin = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(plugin)


class MeshtasticNormalizationTests(unittest.TestCase):
    def node(self, **overrides):
        node = {
            "num": 0x1234ABCD,
            "user": {"id": "!1234abcd", "longName": "Hill relay", "hwModel": "TBEAM"},
            "position": {
                "latitude": 49.6116,
                "longitude": 6.1319,
                "time": 1786183200,
                "groundTrack": 361,
                "groundSpeed": 2.5,
            },
            "deviceMetrics": {"batteryLevel": 87, "voltage": 4.1, "airUtilTx": 0.5},
            "snr": 6.75,
            "hopsAway": 2,
        }
        node.update(overrides)
        return node

    def test_normalizes_node_for_position_api(self):
        report = plugin.node_to_position(self.node())
        self.assertEqual(report["device_id"], "meshtastic:!1234abcd")
        self.assertEqual(report["designation"], "Hill relay")
        self.assertEqual(report["heading"], 1.0)
        self.assertEqual(report["speed"], 9.0)
        self.assertIn("battery 87%", report["status_text"])
        self.assertIn("TBEAM", report["status_text"])
        self.assertLessEqual(len(report["status_text"]), 500)

    def test_accepts_integer_coordinates_and_unknown_user(self):
        node = self.node(
            user={},
            position={"latitudeI": 496116000, "longitudeI": 61319000},
        )
        report = plugin.node_to_position(node, now=1786183200)
        self.assertEqual(report["device_id"], "meshtastic:!1234abcd")
        self.assertAlmostEqual(report["latitude"], 49.6116)
        self.assertAlmostEqual(report["longitude"], 6.1319)

    def test_ignores_nodes_without_valid_position(self):
        self.assertIsNone(plugin.node_to_position(self.node(position={})))
        self.assertIsNone(
            plugin.node_to_position(self.node(position={"latitude": 91, "longitude": 6}))
        )

    def test_reads_telemetry_from_device_metrics_not_position(self):
        report = plugin.node_to_position(self.node(position={
            "latitude": 49.6, "longitude": 6.1, "batteryLevel": 5
        }))
        self.assertIn("battery 87%", report["status_text"])
        self.assertNotIn("battery 5%", report["status_text"])

    def test_node_update_accepts_current_meshtastic_arguments(self):
        adapter = plugin.MeshtasticAdapter("http://localhost/positions", 30)
        interface = object()
        adapter.on_node_updated(node=self.node(), interface=interface)
        self.assertIs(adapter.interface, interface)
        self.assertTrue(adapter.changed.is_set())


if __name__ == "__main__":
    unittest.main()
