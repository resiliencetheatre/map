import * as maplibregl from "/maplibre/maplibre-gl.mjs";

const dot = document.querySelector("#status-dot");
const label = document.querySelector("#status-text");
const mapMessage = document.querySelector("#map-message");

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

Promise.all([
  archive.getHeader(),
  fetch("/styles/situation.json").then((response) => {
    if (!response.ok) throw new Error("Map style request failed");
    return response.json();
  })
])
  .then(([header, style]) => {
    // The archive URL needs the current origin; all other style paths are local.
    style.sources.protomaps.url = `pmtiles://${archiveUrl}`;

    const map = new maplibregl.Map({
      container: "map",
      center: [header.centerLon, header.centerLat],
      zoom: Math.max(header.minZoom, Math.min(header.centerZoom, 3)),
      style
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => mapMessage.classList.add("hidden"));
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
