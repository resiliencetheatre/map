#!/usr/bin/env python3
"""Fly the shared Situation camera along a GeoJSON route (standard library only)."""

import argparse
import bisect
import json
import math
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

EARTH_RADIUS = 6371008.8


def route_points(data):
    """Read line geometries in file order; reject disconnected route sections."""
    lines = []

    def visit(item):
        if not isinstance(item, dict):
            raise ValueError("GeoJSON must contain geometry objects")
        kind = item.get("type")
        if kind == "FeatureCollection":
            features = item.get("features")
            if not isinstance(features, list):
                raise ValueError("FeatureCollection features must be an array")
            for feature in features:
                visit(feature)
        elif kind == "Feature":
            visit(item.get("geometry"))
        elif kind == "LineString":
            lines.append(item.get("coordinates"))
        elif kind == "MultiLineString":
            coordinates = item.get("coordinates")
            if not isinstance(coordinates, list):
                raise ValueError("MultiLineString coordinates must be an array")
            lines.extend(coordinates)
        else:
            raise ValueError("Route must contain only LineString or MultiLineString geometries")

    visit(data)
    points = []
    for line in lines:
        if not isinstance(line, list) or len(line) < 2:
            raise ValueError("Each line must contain at least two coordinates")
        for index, coordinate in enumerate(line):
            if not isinstance(coordinate, list) or len(coordinate) < 2:
                raise ValueError("Coordinates must be [longitude, latitude]")
            lon, lat = coordinate[:2]
            if any(isinstance(v, bool) or not isinstance(v, (int, float))
                   or not math.isfinite(v) for v in (lon, lat)):
                raise ValueError("Coordinates must be finite numbers")
            if not -180 <= lon <= 180 or not -85 <= lat <= 85:
                raise ValueError("Route coordinates exceed longitude ±180 or latitude ±85")
            point = (lon, lat)
            if index == 0 and points and point != points[-1]:
                raise ValueError("Route sections must connect in file order")
            if not points or point != points[-1]:
                points.append(point)
    if len(points) < 2:
        raise ValueError("Route needs at least two distinct points")
    return points


def leg(start, end):
    lon1, lat1, lon2, lat2 = map(math.radians, (*start, *end))
    delta = lon2 - lon1
    a = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(delta / 2) ** 2
    angle = 2 * math.asin(math.sqrt(max(0, min(1, a))))
    if angle >= math.pi - 1e-8:
        raise ValueError("Antipodal route points need an intermediate waypoint")
    bearing = math.atan2(math.sin(delta) * math.cos(lat2),
                         math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))
    return angle * EARTH_RADIUS, math.degrees(bearing) % 360


class Route:
    def __init__(self, points):
        self.points = [points[0]]
        self.distances = [0.0]
        self.bearings = []
        for point in points[1:]:
            distance, bearing = leg(self.points[-1], point)
            if distance < 1e-6:
                continue
            self.points.append(point)
            self.distances.append(self.distances[-1] + distance)
            self.bearings.append(bearing)
        if not self.bearings:
            raise ValueError("Route has zero length")
        self.length = self.distances[-1]

    def sample(self, distance):
        distance = max(0, min(distance, self.length))
        index = min(bisect.bisect_right(self.distances, distance) - 1, len(self.bearings) - 1)
        lon, lat = map(math.radians, self.points[index])
        bearing = math.radians(self.bearings[index])
        angle = (distance - self.distances[index]) / EARTH_RADIUS
        latitude = math.asin(max(-1, min(1, math.sin(lat) * math.cos(angle)
                            + math.cos(lat) * math.sin(angle) * math.cos(bearing))))
        longitude = lon + math.atan2(math.sin(bearing) * math.sin(angle) * math.cos(lat),
                                    math.cos(angle) - math.sin(lat) * math.sin(latitude))
        point = ((math.degrees(longitude) + 180) % 360 - 180, math.degrees(latitude))
        if abs(point[1]) > 85:
            raise ValueError("Route crosses beyond the supported latitude ±85")
        heading = (leg(point, self.points[index + 1])[1]
                   if distance < self.distances[index + 1] - 1e-6
                   else (leg(self.points[index + 1], self.points[index])[1] + 180) % 360)
        return {"longitude": point[0], "latitude": point[1], "bearing": heading}

    def viewpoint(self, distance, turn_distance):
        """Face along a moving route window to turn gradually at vertices."""
        point = self.sample(distance)
        if turn_distance > 0:
            before = self.sample(distance - turn_distance / 2)
            after = self.sample(distance + turn_distance / 2)
            start = (before["longitude"], before["latitude"])
            end = (after["longitude"], after["latitude"])
            length, bearing = leg(start, end)
            if length > 1e-6:
                point["bearing"] = bearing
        return point


def post(url, viewpoint):
    request = Request(url, data=json.dumps(viewpoint).encode(),
                      headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=5) as response:
        if response.status != 200:
            raise RuntimeError(f"server returned HTTP {response.status}")


def make_viewpoint(route, distance, args):
    if args.altitude is None:
        viewpoint = route.sample(distance)
        del viewpoint["bearing"]
    else:
        viewpoint = route.viewpoint(distance, args.speed / 3.6 * args.turn_seconds)
        viewpoint.update(altitude=args.altitude, tilt=args.tilt)
    viewpoint.update(smoothing=args.smoothing, duration=args.interval)
    return viewpoint


def playback_command(route, args):
    """Build a bounded timeline once; browsers interpolate using their own clock."""
    if len(route.points) > 10000:
        raise ValueError("Playback supports at most 10000 route vertices")
    speed = args.speed / 3.6
    duration = route.length / speed
    spacing = max(args.interval, duration / (19999 - len(route.points)))
    distances = set(route.distances)
    for index in range(1, math.ceil(duration / spacing)):
        distances.add(min(index * spacing * speed, route.length))
    frames = []
    for distance in sorted(distances):
        point = make_viewpoint(route, distance, args)
        frames.append([distance / speed, point["longitude"], point["latitude"], point.get("bearing", 0)])
    return {**make_viewpoint(route, 0, args), "playback": frames}


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("geojson", type=Path, help="GeoJSON route file")
    parser.add_argument("--tilt", type=float, help="degrees from vertical, 0–85; use with --altitude")
    parser.add_argument("--altitude", type=float, help="camera metres above sea level; omit both camera options to pan only")
    parser.add_argument("--speed", type=float, default=120, help="route speed in km/h (default: 120)")
    parser.add_argument("--interval", type=float, default=0.1, help="timeline sample seconds (stream update seconds), 0.1–10 (default: 0.1)")
    parser.add_argument("--stream", action="store_true", help="use legacy per-position HTTP updates instead of browser playback")
    parser.add_argument("--smoothing", type=float, default=0.5,
                        help="camera following delay in seconds, 0 disables (default: 0.5)")
    parser.add_argument("--turn-seconds", type=float, default=2,
                        help="route window for gradual turns, 0 disables (default: 2)")
    parser.add_argument("--url", default="http://127.0.0.1:8080/api/viewpoint")
    args = parser.parse_args()
    if (args.tilt is None) != (args.altitude is None):
        parser.error("supply --tilt and --altitude together, or omit both to pan only")
    for name, low, high in (("tilt", 0, 85), ("altitude", 1, 10000000),
                            ("speed", 0.001, 1000000), ("interval", 0.1, 10),
                            ("smoothing", 0, 5), ("turn_seconds", 0, 60)):
        value = getattr(args, name)
        if value is None:
            continue
        if not math.isfinite(value) or not low <= value <= high:
            parser.error(f"--{name} must be between {low} and {high}")
    return args


def main():
    args = parse_args()
    try:
        route = Route(route_points(json.loads(args.geojson.read_text())))
        speed = args.speed / 3.6
        print(f"Flying {route.length / 1000:.2f} km at {args.speed:g} km/h; open the Situation map.")
        if not args.stream:
            command = playback_command(route, args)
            post(args.url, command)
            started = time.monotonic()
            duration = route.length / speed
            try:
                while time.monotonic() - started < duration:
                    time.sleep(min(0.5, max(0, duration - (time.monotonic() - started))))
            except KeyboardInterrupt:
                point = make_viewpoint(route, min((time.monotonic() - started) * speed, route.length), args)
                post(args.url, point)
                print("Flight stopped.")
                return
            print("Flight complete.")
            return
        started = time.monotonic()
        first = True
        while True:
            tick = time.monotonic()
            distance = min((tick - started) * speed, route.length)
            viewpoint = make_viewpoint(route, 0 if first else distance, args)
            viewpoint["duration"] = 0 if first else args.interval
            post(args.url, viewpoint)
            first = False
            if distance >= route.length:
                break
            deadline = min(tick + args.interval, started + route.length / speed)
            time.sleep(max(0, deadline - time.monotonic()))
        print("Flight complete.")
    except KeyboardInterrupt:
        print("Flight stopped.")
    except (OSError, ValueError, URLError, RuntimeError) as error:
        raise SystemExit(f"Flight failed: {error}") from error


if __name__ == "__main__":
    main()
