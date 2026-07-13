import * as maplibregl from "/maplibre/maplibre-gl.mjs";

const dot = document.querySelector("#status-dot");
const label = document.querySelector("#status-text");
const mapMessage = document.querySelector("#map-message");
const activityList = document.querySelector("#activity-list");
const positionSummary = document.querySelector("#position-summary");
const tailLengthInput = document.querySelector("#tail-length");
const tailLengthValue = document.querySelector("#tail-length-value");

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
const visibleTails = new Set();
const tailColors = new Map();
let fittedToLivePositions = false;
let positionRequestRunning = false;
let tailRequestRunning = false;

tailLengthInput.addEventListener("input", () => {
  tailLengthValue.value = `${tailLengthInput.value} s`;
});

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
  const renderedSymbol = new window.ms.Symbol(live.position.sidc, {
    size: 32,
    uniqueDesignation: label
  });
  const symbol = renderedSymbol.asCanvas();
  const size = renderedSymbol.getSize();
  const anchor = renderedSymbol.getAnchor();
  live.marker.setOffset([size.width / 2 - anchor.x, size.height / 2 - anchor.y]);
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

function tailColor(deviceId) {
  if (!tailColors.has(deviceId)) {
    const hue = (tailColors.size * 137.508 + 6) % 360;
    tailColors.set(deviceId, `hsl(${hue.toFixed(1)} 78% 60%)`);
  }
  return tailColors.get(deviceId);
}

function emptyTailData() {
  return { type: "FeatureCollection", features: [] };
}

async function refreshTails(map) {
  if (tailRequestRunning) return;
  if (!visibleTails.size) {
    map.getSource("target-tails")?.setData(emptyTailData());
    return;
  }
  tailRequestRunning = true;
  try {
    const seconds = Number(tailLengthInput.value);
    const response = await fetch(`/api/positions/tails?seconds=${seconds}`, { cache: "no-store" });
    if (!response.ok) throw new Error("Tail request failed");
    const { positions } = await response.json();
    const grouped = new Map();
    positions.filter((position) => visibleTails.has(position.device_id)).forEach((position) => {
      const points = grouped.get(position.device_id) || [];
      points.push(position);
      grouped.set(position.device_id, points);
    });
    const features = [];
    grouped.forEach((points, deviceId) => {
      const color = tailColor(deviceId);
      if (points.length > 1) {
        features.push({
          type: "Feature",
          properties: { kind: "line", color },
          geometry: { type: "LineString", coordinates: points.map((point) => [point.longitude, point.latitude]) }
        });
      }
      points.forEach((point) => features.push({
        type: "Feature",
        properties: {
          kind: "point",
          color,
          designation: point.designation,
          timestamp: point.timestamp
        },
        geometry: { type: "Point", coordinates: [point.longitude, point.latitude] }
      }));
    });
    map.getSource("target-tails")?.setData({ type: "FeatureCollection", features });
  } catch (error) {
    console.warn("Tails:", error);
  } finally {
    tailRequestRunning = false;
  }
}

function updateActivity(map, positions) {
  activityList.replaceChildren(...positions.map((position) => {
    const row = document.createElement("div");
    row.className = "activity-item";
    const marker = document.createElement("span");
    marker.className = "activity-marker";
    marker.style.backgroundColor = tailColor(position.device_id);
    const details = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = position.designation;
    const time = document.createElement("time");
    time.textContent = `${position.speed.toFixed(1)} km/h · ${position.heading.toFixed(0)}°`;
    details.append(name, time);
    const tailButton = document.createElement("button");
    tailButton.className = "tail-toggle";
    tailButton.type = "button";
    tailButton.textContent = "Tail";
    tailButton.setAttribute("aria-pressed", String(visibleTails.has(position.device_id)));
    tailButton.addEventListener("click", () => {
      if (visibleTails.has(position.device_id)) visibleTails.delete(position.device_id);
      else visibleTails.add(position.device_id);
      tailButton.setAttribute("aria-pressed", String(visibleTails.has(position.device_id)));
      refreshTails(map);
    });
    row.append(marker, details, tailButton);
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
    updateActivity(map, positions);
    refreshTails(map);

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
      map.addSource("target-tails", { type: "geojson", data: emptyTailData() });
      map.addLayer({
        id: "target-tail-lines",
        type: "line",
        source: "target-tails",
        filter: ["==", ["get", "kind"], "line"],
        paint: { "line-color": ["get", "color"], "line-width": 2 }
      });
      map.addLayer({
        id: "target-tail-points",
        type: "circle",
        source: "target-tails",
        filter: ["==", ["get", "kind"], "point"],
        paint: {
          "circle-color": ["get", "color"],
          "circle-radius": 2,
          "circle-stroke-color": "#101820",
          "circle-stroke-width": 0.5
        }
      });
      map.on("click", "target-tail-points", (event) => {
        const feature = event.features?.[0];
        if (!feature) return;
        const content = document.createElement("div");
        const name = document.createElement("strong");
        name.textContent = feature.properties.designation;
        const timestamp = document.createElement("div");
        timestamp.textContent = new Date(feature.properties.timestamp).toLocaleString();
        content.append(name, timestamp);
        new maplibregl.Popup({ offset: 6 })
          .setLngLat(feature.geometry.coordinates)
          .setDOMContent(content)
          .addTo(map);
      });
      map.on("mouseenter", "target-tail-points", () => { map.getCanvas().style.cursor = "pointer"; });
      map.on("mouseleave", "target-tail-points", () => { map.getCanvas().style.cursor = ""; });
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
