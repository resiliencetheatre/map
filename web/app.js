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

const sampleSymbols = [
  {
    sidc: "SFGPUCI----K---",
    name: "Friendly infantry",
    designation: "ALPHA 1",
    coordinates: [6.13, 49.61]
  },
  {
    sidc: "SHGPUCA----K---",
    name: "Hostile armor",
    designation: "RED 2",
    coordinates: [6.42, 49.72]
  },
  {
    sidc: "SNGPUCR----K---",
    name: "Neutral reconnaissance",
    designation: "ECHO 3",
    coordinates: [5.84, 49.48]
  }
];

function addSampleSymbols(map) {
  sampleSymbols.forEach((sample) => {
    const element = new window.ms.Symbol(sample.sidc, {
      size: 32,
      uniqueDesignation: sample.designation
    }).asCanvas();
    element.classList.add("military-symbol");
    element.setAttribute("aria-label", sample.name);

    const popup = new maplibregl.Popup({ offset: 24 }).setText(
      `${sample.name} — ${sample.designation}`
    );
    new maplibregl.Marker({ element, anchor: "center" })
      .setLngLat(sample.coordinates)
      .setPopup(popup)
      .addTo(map);
  });
}

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
    map.on("load", () => {
      addSampleSymbols(map);
      map.fitBounds([[5.75, 49.4], [6.5, 49.8]], {
        padding: 60,
        maxZoom: 7,
        duration: 0
      });
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
