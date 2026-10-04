// Critically damped camera follower. New network samples change the target,
// preserving position and velocity; rendering runs independently at frame rate.
const fields = ["longitude", "latitude", "altitude", "bearing", "tilt"];
const wrapped = new Set(["longitude", "bearing"]);

export function samplePlayback(command, seconds) {
  const frames = command.playback;
  const time = Math.max(0, Math.min(seconds, frames.at(-1)[0]));
  let low = 0;
  let high = frames.length - 1;
  while (high - low > 1) {
    const middle = (low + high) >> 1;
    if (frames[middle][0] <= time) low = middle;
    else high = middle;
  }
  const a = frames[low];
  const b = frames[high];
  const fraction = (time - a[0]) / (b[0] - a[0]);
  const result = { ...command };
  delete result.playback;
  for (const [index, key] of [[1, "longitude"], [2, "latitude"], [3, "bearing"]]) {
    if (key === "bearing" && !("altitude" in command)) continue;
    let delta = b[index] - a[index];
    if (wrapped.has(key)) delta = ((delta + 180) % 360 + 360) % 360 - 180;
    result[key] = a[index] + delta * fraction;
  }
  return result;
}

export class ViewpointFollower {
  constructor() {
    this.position = null;
    this.velocity = {};
  }

  setTarget(target, snap = false) {
    const modeChanged = this.target && ("altitude" in this.target) !== ("altitude" in target);
    this.target = { ...target };
    if (!this.position || snap || modeChanged) {
      this.position = { ...target };
      this.velocity = Object.fromEntries(fields.map((key) => [key, 0]));
    }
  }

  step(seconds) {
    const omega = 2 / Math.max(this.target.smoothing, 0.01);
    const decay = Math.exp(-omega * seconds);
    for (const key of fields) {
      if (!(key in this.target)) continue;
      let offset = this.position[key] - this.target[key];
      if (wrapped.has(key)) offset = ((offset + 180) % 360 + 360) % 360 - 180;
      const coefficient = this.velocity[key] + omega * offset;
      this.position[key] = this.target[key] + (offset + coefficient * seconds) * decay;
      this.velocity[key] = (this.velocity[key] - omega * coefficient * seconds) * decay;
    }
    return this.position;
  }
}

export function createViewpointController(map) {
  const follower = new ViewpointFollower();
  let frame = null;
  let previousTime = 0;
  let lastUpdate = 0;
  let playback = null;
  let playbackStarted = 0;
  let savedGroundClamp = null;

  function holdElevation() {
    if (savedGroundClamp !== null) return;
    // Hold for the whole route, including terrain enabled midway through it.
    // Per-frame easing otherwise re-solves camera height as DEM tiles arrive.
    savedGroundClamp = map.getCenterClampedToGround();
    map.setCenterClampedToGround(false);
  }

  function restoreElevation() {
    if (savedGroundClamp === null) return;
    map.setCenterClampedToGround(savedGroundClamp);
    savedGroundClamp = null;
  }

  function camera(viewpoint) {
    if (!("altitude" in viewpoint)) {
      return { center: [viewpoint.longitude, viewpoint.latitude] };
    }
    return map.calculateCameraOptionsFromCameraLngLatAltRotation(
      [viewpoint.longitude, viewpoint.latitude], viewpoint.altitude,
      viewpoint.bearing, viewpoint.tilt
    );
  }

  function stop() {
    if (frame !== null) cancelAnimationFrame(frame);
    frame = null;
    playback = null;
    restoreElevation();
  }

  function move(position) {
    // Keep a single movement lifecycle open, avoiding moveend/tile work each frame.
    // The timeline already interpolated this position. Apply it on the next map
    // frame while keeping the native ease alive until the next timeline frame.
    map.easeTo({ ...camera(position), duration: 100, easing: () => 1, essential: true,
      easeId: "route-playback", freezeElevation: true });
  }

  function render(now) {
    if (playback) {
      const elapsed = Math.max(0, (now - playbackStarted) / 1000);
      const target = samplePlayback(playback, elapsed);
      follower.setTarget(target);
      if (elapsed <= playback.playback.at(-1)[0]) lastUpdate = now;
    }
    const position = follower.target.smoothing
      ? follower.step(Math.max(0, (now - previousTime) / 1000)) : follower.target;
    previousTime = now;
    // Finish exactly on the final command, and release the camera when idle.
    if (now - lastUpdate > Math.max(1, follower.target.smoothing * 10) * 1000) {
      map.jumpTo(camera(follower.target));
      stop();
      return;
    }
    move(position);
    frame = requestAnimationFrame(render);
  }

  map.on("movestart", (event) => { if (event.originalEvent) stop(); });
  map.on("remove", stop);

  return (viewpoint, first, elapsed = 0) => {
    if (viewpoint.playback) {
      stop();
      playback = viewpoint;
      lastUpdate = performance.now();
      playbackStarted = lastUpdate - elapsed * 1000;
      follower.setTarget(samplePlayback(viewpoint, elapsed), true);
      map.stop();
      holdElevation();
      map.jumpTo(camera(follower.position));
      previousTime = lastUpdate;
      frame = requestAnimationFrame(render);
      return;
    }
    playback = null;
    if (!viewpoint.smoothing) {
      stop();
      map.easeTo({ ...camera(viewpoint), duration: first ? 0 : viewpoint.duration * 1000,
        easing: (t) => t, essential: true });
      return;
    }
    const idle = frame === null;
    follower.setTarget(viewpoint, first || idle);
    lastUpdate = performance.now();
    if (idle) {
      map.stop();
      holdElevation();
      map.jumpTo(camera(follower.position));
      previousTime = lastUpdate;
      frame = requestAnimationFrame(render);
    }
  };
}
