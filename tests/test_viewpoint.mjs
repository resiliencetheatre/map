import assert from "node:assert/strict";
import test from "node:test";
import { ViewpointFollower, createViewpointController, samplePlayback } from "../web/viewpoint.mjs";

const point = (overrides = {}) => ({longitude: 0, latitude: 0, altitude: 1000,
  bearing: 0, tilt: 60, smoothing: 0.5, duration: 0.1, ...overrides});

test("irregular network samples keep the camera moving between updates", () => {
  const follower = new ViewpointFollower();
  follower.setTarget(point());
  let nextUpdate = 0;
  let previous = 0;
  const speeds = [];
  for (let frame = 1; frame <= 600; frame++) {
    const seconds = frame / 60;
    if (seconds >= nextUpdate) {
      follower.setTarget(point({longitude: seconds * 0.001}));
      nextUpdate = seconds + (frame % 2 ? 0.1 : 0.15);
    }
    const current = follower.step(1 / 60).longitude;
    if (seconds > 2) speeds.push((current - previous) * 60);
    previous = current;
  }
  assert.ok(Math.min(...speeds) > 0.0008, "no pauses between samples");
  assert.ok(Math.max(...speeds) < 0.0012, "no catch-up speed spikes");
});

test("new target preserves velocity; stationary final target settles", () => {
  const follower = new ViewpointFollower();
  follower.setTarget(point());
  follower.setTarget(point({longitude: 1}));
  follower.step(0.1);
  const velocity = follower.velocity.longitude;
  const longitude = follower.position.longitude;
  follower.setTarget(point({longitude: 2}));
  assert.equal(follower.velocity.longitude, velocity);
  assert.equal(follower.position.longitude, longitude);
  for (let i = 0; i < 600; i++) follower.step(1 / 60);
  assert.ok(Math.abs(follower.position.longitude - 2) < 1e-9);
});

test("bearing and longitude take the short path across wrap boundaries", () => {
  const follower = new ViewpointFollower();
  follower.setTarget(point({longitude: 179.9, bearing: 359}));
  follower.setTarget(point({longitude: -179.9, bearing: 1}));
  const result = follower.step(0.1);
  assert.ok(Math.abs(result.longitude) > 179);
  assert.ok(Math.abs(result.bearing) < 2);
});

test("camera renders between commands, finishes exactly and releases its frame", () => {
  const frames = new Map();
  const events = new Map();
  let counter = 0;
  let lastCamera;
  let groundClamped = true;
  const originalRequest = globalThis.requestAnimationFrame;
  const originalCancel = globalThis.cancelAnimationFrame;
  globalThis.requestAnimationFrame = (callback) => { frames.set(++counter, callback); return counter; };
  globalThis.cancelAnimationFrame = (id) => frames.delete(id);
  const map = {
    on: (name, callback) => events.set(name, callback),
    stop() {},
    getCenterClampedToGround: () => groundClamped,
    setCenterClampedToGround: (value) => { groundClamped = value; },
    calculateCameraOptionsFromCameraLngLatAltRotation: (center, altitude, bearing, pitch) =>
      ({center, altitude, bearing, pitch}),
    jumpTo: (options) => { lastCamera = options; },
    easeTo: (options) => { lastCamera = options; }
  };
  try {
    const apply = createViewpointController(map);
    apply(point(), true);
    assert.equal(groundClamped, false, "playback holds elevation before moving");
    apply(point({longitude: 1}), false);
    function frame(time) {
      const [id, callback] = frames.entries().next().value;
      frames.delete(id);
      callback(time);
    }
    frame(performance.now() + 100);
    assert.equal(lastCamera.freezeElevation, true);
    assert.ok(lastCamera.center[0] > 0 && lastCamera.center[0] < 1);
    frame(performance.now() + 6000);
    assert.equal(lastCamera.center[0], 1);
    assert.equal(frames.size, 0);
    assert.equal(groundClamped, true, "completion restores terrain following");
    apply(point({smoothing: 0}), false);
    assert.equal(lastCamera.duration, 100);
    apply(point(), false);
    events.get("movestart")({originalEvent: {type: "mousedown"}});
    assert.equal(frames.size, 0);
    assert.equal(groundClamped, true, "manual navigation restores terrain following");
    const pan = {longitude: 6, latitude: 49, smoothing: 0.5, duration: 0.1};
    apply(pan, false);
    assert.deepEqual(lastCamera, {center: [6, 49]});
    apply({...pan, longitude: 7}, false);
    frame(performance.now() + 100);
    for (const key of ["altitude", "bearing", "pitch", "zoom"]) assert.ok(!(key in lastCamera));
    assert.equal(lastCamera.easeId, "route-playback");
    assert.equal(lastCamera.duration, 100);
    assert.equal(lastCamera.easing(0.2), 1);
    assert.ok(lastCamera.center[0] > 6 && lastCamera.center[0] < 7);
    // Switching back to full flight must initialize all camera fields.
    apply(point(), false);
    frame(performance.now() + 200);
    assert.equal(lastCamera.altitude, 1000);
    assert.ok(Number.isFinite(lastCamera.bearing));
    events.get("remove")();
    assert.equal(frames.size, 0);
    assert.equal(groundClamped, true, "removal releases the elevation hold");
    const playback = {...pan, smoothing: 0, playback: [[0, 6, 49, 0], [10, 7, 49, 0]]};
    apply(playback, true, 5);
    assert.equal(groundClamped, false, "centre-only playback also holds elevation");
    assert.equal(lastCamera.center[0], 6.5);
    frame(performance.now() + 1000);
    assert.ok(lastCamera.center[0] > 6.59 && lastCamera.center[0] < 6.62);
    events.get("remove")();
    // Preserve maps deliberately configured not to follow terrain.
    groundClamped = false;
    apply(playback, true, 5);
    events.get("movestart")({originalEvent: {type: "mousedown"}});
    assert.equal(groundClamped, false);
  } finally {
    globalThis.requestAnimationFrame = originalRequest;
    globalThis.cancelAnimationFrame = originalCancel;
  }
});

test("local playback interpolates wrap boundaries and clamps to endpoints", () => {
  const command = {...point(), playback: [[0, 179, 0, 359], [10, -179, 2, 1]]};
  const middle = samplePlayback(command, 5);
  assert.equal(middle.longitude, 180);
  assert.equal(middle.latitude, 1);
  assert.equal(middle.bearing, 360);
  assert.equal(samplePlayback(command, -10).longitude, 179);
  assert.equal(samplePlayback(command, 20).latitude, 2);
});
