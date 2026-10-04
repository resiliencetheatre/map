import importlib.util
import json
import math
import unittest
from pathlib import Path
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location("python_fly", Path(__file__).resolve().parents[1] / "python-fly.py")
fly = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fly)


class RouteTests(unittest.TestCase):
    def test_nested_connected_route_and_duplicate_vertices(self):
        data = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {
            "type": "MultiLineString", "coordinates": [
                [[6, 49, 100], [6, 49], [7, 49]], [[7, 49], [7, 50]]
            ]}}]}
        self.assertEqual(fly.route_points(data), [(6, 49), (7, 49), (7, 50)])

    def test_invalid_routes(self):
        for data in (
            {"type": "Point", "coordinates": [6, 49]},
            {"type": "FeatureCollection", "features": None},
            {"type": "LineString", "coordinates": [[6, 49], [6, 49]]},
            {"type": "LineString", "coordinates": [[6, 49], [math.nan, 50]]},
            {"type": "LineString", "coordinates": [[6, 49], [6, 90]]},
            {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 0]], [[2, 0], [3, 0]]]},
        ):
            with self.subTest(data=data), self.assertRaises(ValueError):
                fly.route_points(data)

    def test_distance_interpolation_and_heading(self):
        route = fly.Route([(0, 0), (1, 0), (1, 1)])
        self.assertAlmostEqual(route.length, 222390.16, delta=1)
        halfway = route.sample(route.distances[1] / 2)
        self.assertAlmostEqual(halfway["longitude"], 0.5)
        self.assertAlmostEqual(halfway["latitude"], 0)
        self.assertAlmostEqual(halfway["bearing"], 90)
        corner = route.sample(route.distances[1])
        self.assertAlmostEqual(corner["bearing"], 0)
        end = route.sample(route.length + 100)
        self.assertAlmostEqual(end["longitude"], 1)
        self.assertAlmostEqual(end["latitude"], 1)

    def test_antimeridian_uses_short_path(self):
        route = fly.Route([(179, 0), (-179, 0)])
        self.assertAlmostEqual(abs(route.sample(route.length / 2)["longitude"]), 180)
        self.assertLess(route.length, 223000)

    def test_heading_turns_gradually_at_vertex(self):
        route = fly.Route([(0, 0), (0.01, 0), (0.01, 0.01)])
        corner = route.distances[1]
        before = route.viewpoint(corner - 1, 200)
        after = route.viewpoint(corner + 1, 200)
        self.assertLess(abs(before["bearing"] - after["bearing"]), 2)
        self.assertAlmostEqual(route.viewpoint(corner, 200)["bearing"], 45, delta=0.01)
        self.assertEqual(route.viewpoint(corner, 0), route.sample(corner))

    def test_zero_length_and_antipodal(self):
        for points in ([(180, 0), (-180, 0)], [(0, 0), (180, 0)]):
            with self.assertRaises(ValueError):
                fly.Route(points)

    def test_flight_posts_start_and_exact_finish(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            path.write_text(json.dumps({"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]}))
            with patch("sys.argv", ["python-fly.py", str(path), "--stream", "--speed", "3600", "--tilt", "60", "--altitude", "1000"]), \
                    patch.object(fly.time, "monotonic", side_effect=[0, 0, 0, 1]), \
                    patch.object(fly.time, "sleep"), patch.object(fly, "post") as post:
                fly.main()
            self.assertEqual(post.call_count, 2)
            self.assertEqual(post.call_args_list[0].args[1]["longitude"], 0)
            self.assertAlmostEqual(post.call_args.args[1]["longitude"], 0.001)
            self.assertEqual(post.call_args.args[1]["tilt"], 60)
            self.assertEqual(post.call_args.args[1]["smoothing"], 0.5)

    def test_pan_posts_only_centre(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "route.json"
            path.write_text(json.dumps({"type": "LineString", "coordinates": [[0, 0], [0.001, 0]]}))
            with patch("sys.argv", ["python-fly.py", str(path), "--stream"]), \
                    patch.object(fly.time, "monotonic", side_effect=[0, 0, 0, 100]), \
                    patch.object(fly.time, "sleep"), patch.object(fly, "post") as post:
                fly.main()
            for call in post.call_args_list:
                self.assertEqual(set(call.args[1]), {"longitude", "latitude", "duration", "smoothing"})

    def test_partial_camera_options_rejected(self):
        for option in ("--tilt", "--altitude"):
            with patch("sys.argv", ["python-fly.py", "route.json", option, "60"]), \
                    patch("sys.stderr"), self.assertRaises(SystemExit):
                fly.parse_args()

    def test_browser_playback_uploads_once(self):
        path = Path(__file__).resolve().parents[1] / "examples/flight-route-new-taipei.geojson"
        with patch("sys.argv", ["python-fly.py", str(path)]), \
                patch.object(fly.time, "monotonic", side_effect=[0, 10000]), \
                patch.object(fly, "post") as post:
            fly.main()
        self.assertEqual(post.call_count, 1)
        command = post.call_args.args[1]
        frames = command["playback"]
        self.assertEqual(frames[0][0], 0)
        self.assertLessEqual(len(frames), 20000)
        self.assertTrue(all(a[0] < b[0] for a, b in zip(frames, frames[1:])))
        self.assertAlmostEqual(frames[-1][1], frames[0][1])
        self.assertNotIn("altitude", command)

    def test_long_route_payload_is_bounded(self):
        with patch("sys.argv", ["python-fly.py", "route.json", "--speed", "1"]):
            args = fly.parse_args()
        command = fly.playback_command(fly.Route([(0, 0), (10, 0)]), args)
        self.assertLessEqual(len(command["playback"]), 20000)
        self.assertLess(len(json.dumps(command).encode()), 4 * 1024 * 1024)

    def test_interrupt_sends_stop_without_playback(self):
        path = Path(__file__).resolve().parents[1] / "examples/flight-route-new-taipei.geojson"
        with patch("sys.argv", ["python-fly.py", str(path)]), \
                patch.object(fly.time, "monotonic", side_effect=[0, 0, 0, 1]), \
                patch.object(fly.time, "sleep", side_effect=KeyboardInterrupt), \
                patch.object(fly, "post") as post:
            fly.main()
        self.assertEqual(post.call_count, 2)
        self.assertIn("playback", post.call_args_list[0].args[1])
        self.assertNotIn("playback", post.call_args.args[1])


if __name__ == "__main__":
    unittest.main()
