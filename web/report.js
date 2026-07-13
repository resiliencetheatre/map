import * as maplibregl from "/maplibre/maplibre-gl.mjs";

const DEVICE_ID_KEY = "situation.reporter.deviceId";
const TARGET_NAME_KEY = "situation.reporter.targetName";
const TARGET_SYMBOL_KEY = "situation.reporter.targetSymbol";

const latitudeOutput = document.querySelector("#latitude");
const longitudeOutput = document.querySelector("#longitude");
const zoomOutput = document.querySelector("#zoom");
const deviceIdInput = document.querySelector("#device-id");
const targetNameInput = document.querySelector("#target-name");
const statusInput = document.querySelector("#target-status");
const symbolSelect = document.querySelector("#target-symbol");
const symbolPreview = document.querySelector("#symbol-preview");
const result = document.querySelector("#report-result");
const form = document.querySelector("#report-form");
const locateButton = document.querySelector("#locate");
const mapMessage = document.querySelector("#report-map-message");

function makeDeviceId() {
  if (crypto.randomUUID) return crypto.randomUUID();
  return `browser-${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

const deviceId = localStorage.getItem(DEVICE_ID_KEY) || makeDeviceId();
localStorage.setItem(DEVICE_ID_KEY, deviceId);
deviceIdInput.value = deviceId;
targetNameInput.value = localStorage.getItem(TARGET_NAME_KEY) || `Mobile ${deviceId.slice(0, 6)}`;
targetNameInput.addEventListener("input", () => localStorage.setItem(TARGET_NAME_KEY, targetNameInput.value));

function populateSymbols(config) {
  if (!config || !Array.isArray(config.symbols) || !config.symbols.length) {
    throw new Error("Report symbol configuration must contain at least one symbol");
  }
  const groups = new Map();
  config.symbols.forEach((symbol) => {
    if (!symbol.sidc || !symbol.label) throw new Error("Report symbol entries require sidc and label");
    const groupName = symbol.group || "Other";
    if (!groups.has(groupName)) groups.set(groupName, []);
    groups.get(groupName).push(symbol);
  });
  groups.forEach((symbols, groupName) => {
    const group = document.createElement("optgroup");
    group.label = groupName;
    symbols.forEach((symbol) => group.append(new Option(`${symbol.label} · ${symbol.sidc}`, symbol.sidc)));
    symbolSelect.append(group);
  });
  const saved = localStorage.getItem(TARGET_SYMBOL_KEY);
  symbolSelect.value = config.symbols.some(({ sidc }) => sidc === saved) ? saved : config.symbols[0].sidc;
  renderSymbolPreview();
}

function renderSymbolPreview() {
  const canvas = new window.ms.Symbol(symbolSelect.value, { size: 30 }).asCanvas();
  symbolPreview.replaceChildren(canvas);
}

symbolSelect.addEventListener("change", () => {
  localStorage.setItem(TARGET_SYMBOL_KEY, symbolSelect.value);
  renderSymbolPreview();
});

const protocol = new pmtiles.Protocol();
maplibregl.addProtocol("pmtiles", protocol.tile);

function buildStyle(baseStyle, layers) {
  const style = structuredClone(baseStyle);
  const templateSource = style.sources.protomaps;
  const templates = style.layers;
  style.sources = {};
  style.layers = templates.filter((layer) => !layer.source);
  layers.forEach(({ config, url, header }) => {
    const source = `pmtiles-${config.id}`;
    const common = {
      url: `pmtiles://${url}`,
      minzoom: header.minZoom,
      maxzoom: header.maxZoom,
      bounds: [header.minLon, header.minLat, header.maxLon, header.maxLat]
    };
    if (header.tileType === pmtiles.TileType.Mvt) {
      style.sources[source] = { ...templateSource, ...common };
      templates.filter((layer) => layer.source).forEach((template) => {
        style.layers.push({ ...structuredClone(template), id: `${config.id}--${template.id}`, source });
      });
    } else {
      style.sources[source] = { type: "raster", tileSize: 256, ...common };
      style.layers.push({
        id: `${config.id}--raster`, type: "raster", source,
        minzoom: header.minZoom, paint: { "raster-fade-duration": 0 }
      });
    }
  });
  style.sprite = new URL(style.sprite, location.origin).href;
  if (!/^https?:\/\//.test(style.glyphs)) {
    const path = style.glyphs.startsWith("/") ? style.glyphs : `/${style.glyphs}`;
    style.glyphs = `${location.origin}${path}`;
  }
  return style;
}

function updateCoordinates(map) {
  const center = map.getCenter();
  latitudeOutput.value = center.lat.toFixed(6);
  longitudeOutput.value = center.lng.toFixed(6);
  zoomOutput.value = map.getZoom().toFixed(1);
}

function showResult(message, state = "") {
  result.textContent = message;
  result.className = state;
}

function useBrowserLocation(map) {
  if (!navigator.geolocation) {
    showResult("Geolocation is unavailable; position the crosshair manually.", "error");
    return;
  }
  locateButton.disabled = true;
  showResult("Requesting browser location…");
  navigator.geolocation.getCurrentPosition(
    (position) => {
      map.easeTo({
        center: [position.coords.longitude, position.coords.latitude],
        zoom: Math.max(map.getZoom(), 16),
        duration: 500
      });
      map.reporterAccuracy = position.coords.accuracy || 0;
      map.reporterHeading = position.coords.heading || 0;
      map.reporterSpeed = Math.max(0, (position.coords.speed || 0) * 3.6);
      showResult(`Location found (±${Math.round(position.coords.accuracy)} m).`);
      locateButton.disabled = false;
    },
    (error) => {
      showResult(`${error.message} Position the crosshair manually.`, "error");
      locateButton.disabled = false;
    },
    { enableHighAccuracy: true, timeout: 10000, maximumAge: 5000 }
  );
}

Promise.all([
  fetch("/map-layers.json", { cache: "no-store" }).then((response) => response.json()),
  fetch("/styles/situation.json").then((response) => response.json()),
  fetch("/report-symbols.json", { cache: "no-store" }).then((response) => response.json())
]).then(async ([config, baseStyle, symbolConfig]) => {
  populateSymbols(symbolConfig);
  const layers = await Promise.all(config.layers.map(async (layer) => {
    const url = new URL(`/maps/${encodeURIComponent(layer.archive)}`, location.origin).href;
    const archive = new pmtiles.PMTiles(url);
    protocol.add(archive);
    return { config: layer, url, header: await archive.getHeader() };
  }));
  const base = layers.find(({ config: layer }) => layer.role === "base") || layers[0];
  const map = new maplibregl.Map({
    container: "report-map",
    center: [base.header.centerLon, base.header.centerLat],
    zoom: Math.max(base.header.minZoom, Math.min(base.header.centerZoom, 3)),
    style: buildStyle(baseStyle, layers)
  });
  map.reporterAccuracy = 0;
  map.reporterHeading = 0;
  map.reporterSpeed = 0;
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  map.on("move", () => updateCoordinates(map));
  map.on("dragstart", () => { map.reporterAccuracy = 0; });
  map.on("load", () => {
    updateCoordinates(map);
    mapMessage.classList.add("hidden");
    useBrowserLocation(map);
  });
  locateButton.addEventListener("click", () => useBrowserLocation(map));

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const submit = document.querySelector("#report-position");
    const center = map.getCenter();
    const designation = targetNameInput.value.trim();
    if (!designation) return targetNameInput.focus();
    localStorage.setItem(TARGET_NAME_KEY, designation);
    submit.disabled = true;
    showResult("Reporting position…");
    try {
      const response = await fetch("/api/positions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          run_id: `browser-${deviceId}`,
          device_id: deviceId,
          timestamp: new Date().toISOString(),
          latitude: center.lat,
          longitude: center.lng,
          heading: map.reporterHeading,
          speed: map.reporterSpeed,
          accuracy: map.reporterAccuracy,
          sidc: symbolSelect.value,
          designation,
          status_text: statusInput.value.trim()
        })
      });
      if (!response.ok) {
        const problem = await response.json().catch(() => ({}));
        throw new Error(problem.error || `Server returned ${response.status}`);
      }
      showResult(`Position reported at ${new Date().toLocaleTimeString()}.`, "success");
    } catch (error) {
      showResult(`Report failed: ${error.message}`, "error");
    } finally {
      submit.disabled = false;
    }
  });
}).catch((error) => {
  console.error(error);
  mapMessage.textContent = "Map could not be loaded";
  showResult("Map is unavailable.", "error");
});
