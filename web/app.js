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

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

const liveMarkers = new Map();
let fittedToLivePositions = false;
let positionRequestRunning = false;

function ageInSeconds(position) {
  const updatedAt = Date.parse(position.received_at || position.timestamp);
  return Number.isFinite(updatedAt) ? Math.max(0, Math.floor((Date.now() - updatedAt) / 1000)) : 0;
}

function formatAge(seconds) {
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
}

function renderLiveSymbol(live) {
  const age = ageInSeconds(live.position);
  const label = `${live.position.designation} · age ${formatAge(age)}`;
  const symbol = new window.ms.Symbol(live.position.sidc, {
    size: 32,
    uniqueDesignation: label
  }).asCanvas();
  symbol.classList.add("military-symbol");
  live.element.replaceChildren(symbol);
  live.element.setAttribute("aria-label", label);
}

function createLiveMarker(map, position) {
  const element = document.createElement("div");

  const popup = new maplibregl.Popup({ offset: 24 });
  const marker = new maplibregl.Marker({ element, anchor: "center" })
    .setLngLat([position.longitude, position.latitude])
    .setPopup(popup)
    .addTo(map);
  liveMarkers.set(position.device_id, { marker, popup, element, position, sidc: position.sidc });
  renderLiveSymbol(liveMarkers.get(position.device_id));
  return liveMarkers.get(position.device_id);
}

function updateMarkerAges() {
  liveMarkers.forEach((live) => renderLiveSymbol(live));
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
      live.position = position;
      renderLiveSymbol(live);
      live.marker.setLngLat([position.longitude, position.latitude]);
      live.popup.setText(
        `${position.designation} · age ${formatAge(ageInSeconds(position))} · ` +
        `${position.speed.toFixed(1)} km/h · ${position.heading.toFixed(0)}°`
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

function validateLayerConfig(config) {
  if (!config || !Array.isArray(config.layers) || !config.layers.length) {
    throw new Error("Map layer configuration must contain at least one layer");
  }
  const ids = new Set();
  config.layers.forEach((layer) => {
    if (!layer.id || !/^[a-zA-Z0-9_-]+$/.test(layer.id) || ids.has(layer.id)) {
      throw new Error(`Invalid or duplicate map layer id: ${layer.id}`);
    }
    if (!layer.archive || !["base", "overlay"].includes(layer.role)) {
      throw new Error(`Incomplete map layer: ${layer.id}`);
    }
    ids.add(layer.id);
  });
  if (config.layers.filter((layer) => layer.role === "base").length !== 1) {
    throw new Error("Map layer configuration must contain exactly one base layer");
  }
  return config;
}

function buildLayeredStyle(baseStyle, configuredLayers) {
  const style = structuredClone(baseStyle);
  const templateSource = style.sources.protomaps;
  const templateLayers = style.layers;
  style.sources = {};
  style.layers = templateLayers.filter((layer) => !layer.source);
  configuredLayers.forEach(({ config, url, header }) => {
    const sourceId = `pmtiles-${config.id}`;
    const sourceBounds = [header.minLon, header.minLat, header.maxLon, header.maxLat];
    if (header.tileType === pmtiles.TileType.Mvt) {
      style.sources[sourceId] = {
        ...templateSource,
        url: `pmtiles://${url}`,
        minzoom: header.minZoom,
        maxzoom: header.maxZoom,
        bounds: sourceBounds
      };
      templateLayers.filter((layer) => layer.source).forEach((template) => {
        const layer = structuredClone(template);
        layer.id = `${config.id}--${template.id}`;
        layer.source = sourceId;
        style.layers.push(layer);
      });
    } else {
      style.sources[sourceId] = {
        type: "raster",
        url: `pmtiles://${url}`,
        tileSize: 256,
        minzoom: header.minZoom,
        maxzoom: header.maxZoom,
        bounds: sourceBounds
      };
      style.layers.push({
        id: `${config.id}--raster`,
        type: "raster",
        source: sourceId,
        minzoom: header.minZoom,
        paint: { "raster-fade-duration": 0 }
      });
    }
  });
  return style;
}

Promise.all([
  fetch("/map-layers.json", { cache: "no-store" }).then((response) => {
    if (!response.ok) throw new Error("Map layer configuration request failed");
    return response.json();
  }),
  fetch("/styles/situation.json").then((response) => {
    if (!response.ok) throw new Error("Map style request failed");
    return response.json();
  })
])
  .then(async ([rawConfig, baseStyle]) => {
    const config = validateLayerConfig(rawConfig);
    const configuredLayers = await Promise.all(config.layers.map(async (layer) => {
      const url = new URL(`/maps/${encodeURIComponent(layer.archive)}`, location.origin).href;
      const archive = new pmtiles.PMTiles(url);
      protocol.add(archive);
      return { config: layer, url, header: await archive.getHeader() };
    }));
    const base = configuredLayers.find(({ config: layer }) => layer.role === "base");

    // MapLibre v6 requires absolute protocol, sprite, and glyph URLs.
    const style = buildLayeredStyle(baseStyle, configuredLayers);
    style.sprite = new URL(style.sprite, location.origin).href;
    if (!/^https?:\/\//.test(style.glyphs)) {
      const path = style.glyphs.startsWith("/") ? style.glyphs : `/${style.glyphs}`;
      style.glyphs = `${location.origin}${path}`;
    }

    const map = new maplibregl.Map({
      container: "map",
      center: [base.header.centerLon, base.header.centerLat],
      zoom: Math.max(base.header.minZoom, Math.min(base.header.centerZoom, 3)),
      style
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.on("load", () => {
      refreshPositions(map);
      window.setInterval(() => {
        updateMarkerAges();
        refreshPositions(map);
      }, 1000);
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
