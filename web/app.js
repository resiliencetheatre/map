import * as maplibregl from "/maplibre/maplibre-gl.mjs";

const dot = document.querySelector("#status-dot");
const label = document.querySelector("#status-text");
const mapMessage = document.querySelector("#map-message");
const activityList = document.querySelector("#activity-list");
const positionSummary = document.querySelector("#position-summary");

// Reflect server availability in the compact header indicator.
fetch("/api/status")
  .then((response) => {
    if (!response.ok) throw new Error("Status request failed");
    return response.json();
  })
  .then((data) => {
    dot.className = "status-dot online";
    label.textContent = data.status === "ok" ? "Operational" : "Degraded";
  })
  .catch(() => {
    dot.className = "status-dot offline";
    label.textContent = "Offline";
  });

const archiveUrl = `${location.origin}/maps/planet.pmtiles`;
const protocol = new pmtiles.Protocol();
const archive = new pmtiles.PMTiles(archiveUrl);
protocol.add(archive);
maplibregl.addProtocol("pmtiles", protocol.tile);

const liveMarkers = new Map();
let fittedToLivePositions = false;
let positionRequestRunning = false;

function createLiveMarker(map, position) {
  const element = new window.ms.Symbol(position.sidc, {
    size: 32,
    uniqueDesignation: position.designation
  }).asCanvas();
  element.classList.add("military-symbol");
  element.setAttribute("aria-label", position.designation);

  const popup = new maplibregl.Popup({ offset: 24 });
  const marker = new maplibregl.Marker({ element, anchor: "center" })
    .setLngLat([position.longitude, position.latitude])
    .setPopup(popup)
    .addTo(map);
  liveMarkers.set(position.device_id, { marker, popup, sidc: position.sidc });
  return liveMarkers.get(position.device_id);
}

function updateActivity(positions) {
  activityList.replaceChildren(...positions.map((position) => {
    const row = document.createElement("div");
    row.className = "activity-item";
    const marker = document.createElement("span");
    marker.className = "activity-marker";
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = position.designation;
    const time = document.createElement("time");
    time.textContent = `${position.speed.toFixed(1)} km/h · ${position.heading.toFixed(0)}°`;
    details.append(name, time);
    row.append(marker, details);
    return row;
  }));
  positionSummary.textContent = `${positions.length} live device${positions.length === 1 ? "" : "s"}.`;
}

async function refreshPositions(map) {
  if (positionRequestRunning) return;
  positionRequestRunning = true;
  try {
    const response = await fetch("/api/positions", { cache: "no-store" });
    if (!response.ok) throw new Error("Position request failed");
    const { positions } = await response.json();
    positions.forEach((position) => {
      let live = liveMarkers.get(position.device_id);
      if (live && live.sidc !== position.sidc) {
        live.marker.remove();
        liveMarkers.delete(position.device_id);
        live = null;
      }
      live ||= createLiveMarker(map, position);
      live.marker.setLngLat([position.longitude, position.latitude]);
      live.popup.setText(
        `${position.designation} · ${position.speed.toFixed(1)} km/h · ${position.heading.toFixed(0)}°`
      );
    });
    updateActivity(positions);

    if (positions.length && !fittedToLivePositions) {
      const bounds = new maplibregl.LngLatBounds();
      positions.forEach((position) => bounds.extend([position.longitude, position.latitude]));
      map.fitBounds(bounds, { padding: 80, maxZoom: 10, duration: 0 });
      fittedToLivePositions = true;
    }
  } catch (error) {
    console.warn("Positions:", error);
    positionSummary.textContent = "Position service unavailable.";
  } finally {
    positionRequestRunning = false;
  }
}

Promise.all([
  archive.getHeader(),
  fetch("/styles/situation.json").then((response) => {
    if (!response.ok) throw new Error("Map style request failed");
    return response.json();
  })
])
  .then(([header, style]) => {
    // MapLibre v6 requires absolute protocol, sprite, and glyph URLs.
    style.sources.protomaps.url = `pmtiles://${archiveUrl}`;
    style.sprite = new URL(style.sprite, location.origin).href;
    if (!/^https?:\/\//.test(style.glyphs)) {
      const path = style.glyphs.startsWith("/") ? style.glyphs : `/${style.glyphs}`;
      style.glyphs = `${location.origin}${path}`;
    }

    const map = new maplibregl.Map({
      container: "map",
      center: [header.centerLon, header.centerLat],
      zoom: Math.max(header.minZoom, Math.min(header.centerZoom, 3)),
      style
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => {
      refreshPositions(map);
      window.setInterval(() => refreshPositions(map), 1000);
      mapMessage.classList.add("hidden");
    });
    map.on("error", (event) => {
      // Missing optional glyph ranges and cancelled tiles are recoverable.
      // Keep them visible to developers without covering a usable map.
      console.warn("MapLibre:", event.error);
    });
  })
  .catch((error) => {
    console.error(error);
    mapMessage.textContent = "Map archive could not be opened";
  });
