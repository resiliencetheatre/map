# Situation

Situation is a small, offline-capable situation-awareness web application. A
Python standard-library server delivers the user interface and a local PMTiles
world map to MapLibre GL JS. It does not require Flask, Django, Node.js, npm, a
database, or a build step.

## Requirements

### Server

- Linux or another operating system with Python 3.10 or newer
- Read access to a PMTiles v3 vector archive
- Enough free storage for the map archive (the archive is not included)
- `curl` is optional and is only needed for the verification commands below

Only Python standard-library modules are used: `argparse`, `http.server`,
`json`, `mimetypes`, `pathlib`, `re`, and `urllib.parse`. There is no
`requirements.txt` because no Python packages need to be installed.

### Browser

- A current Firefox, Chromium, Chrome, or other MapLibre-compatible browser
- WebGL enabled, with working graphics drivers
- JavaScript enabled

Internet access is not required at runtime. Map data, JavaScript, CSS, fonts,
sprites, and the map style are all served locally.

The initial map view includes three static milsymbol demonstrations near
Luxembourg: friendly infantry, hostile armor, and neutral reconnaissance.
Selecting a symbol opens its name and example designation.

### Using military symbols

`web/index.html` loads `web/milsymbol.js` before the application module, making
the library available as `window.ms`. Static examples are defined in the
`sampleSymbols` array near the top of `web/app.js`. Each entry contains:

- `sidc`: a MIL-STD-2525/APP-6 Symbol Identification Code
- `name`: the human-readable popup and accessibility label
- `designation`: example unit text rendered with the symbol
- `coordinates`: a MapLibre `[longitude, latitude]` pair

For example:

```js
{
  sidc: "SFGPUCI----K---",
  name: "Friendly infantry",
  designation: "ALPHA 1",
  coordinates: [6.13, 49.61]
}
```

`addSampleSymbols(map)` converts each definition into a canvas and attaches it
to MapLibre:

```js
const element = new window.ms.Symbol(sample.sidc, {
  size: 32,
  uniqueDesignation: sample.designation
}).asCanvas();

new maplibregl.Marker({ element, anchor: "center" })
  .setLngLat(sample.coordinates)
  .setPopup(popup)
  .addTo(map);
```

Add, remove, or relocate examples by editing `sampleSymbols`. The marker setup
runs once in the map's `load` event. These are static browser-side examples;
they are not persisted or supplied by an API. Consult the milsymbol project for
supported SIDCs and rendering options.

## Bundled web dependencies

| Component | Location | Purpose |
| --- | --- | --- |
| MapLibre GL JS `6.0.0-20` | `maplibre-gl-js/` | Interactive WebGL map renderer |
| PMTiles JS `3.2.0` | `web/pmtiles.js` | Registers the `pmtiles://` protocol with MapLibre |
| milsymbol `3.0.4` | `web/milsymbol.js` | Generates MIL-STD-2525/APP-6 tactical symbols |
| Situation style | `web/styles/situation.json` | Bright, MapLibre-v6-compatible vector map style |
| EdgeUI bright style | `web/styles/style-v4.json` | Original style source retained for reference |
| Protomaps sprite atlas | `web/sprites/` | Map icons in standard and high-DPI variants |
| Noto Sans glyphs | `web/fonts/` | Primary Latin regular and italic label glyphs |

MapLibre GL JS and PMTiles JS are BSD-3-Clause projects. milsymbol is MIT
licensed. The map style is adapted from EdgeUI's Protomaps-based bright style;
Protomaps releases its map design under CC0. Noto fonts are distributed under
the SIL Open Font License. OpenStreetMap-derived tiles require visible
OpenStreetMap attribution, which is included in the map style.

## Directory layout

```text
python-front.py             Server entry point
web/                        Application HTML, CSS, JavaScript, and map assets
web/milsymbol.js            Bundled tactical-symbol renderer
web/styles/situation.json   Active map style
maplibre-gl-js/             Bundled MapLibre ES modules and CSS
maps/planet.pmtiles         Required map archive or symlink (not committed)
```

The application expects the vector archive to contain the Protomaps layers
`boundaries`, `buildings`, `earth`, `landcover`, `landuse`, `places`, `pois`,
`roads`, and `water`.

## Setup on another Linux system

1. Copy or clone the complete repository. Do not omit `maplibre-gl-js/` or the
   binary assets under `web/`.

2. Confirm the Python version:

   ```sh
   python3 --version
   ```

   Install Python 3 with the distribution package manager if it is absent. For
   example, Debian and Ubuntu use `sudo apt install python3`; Fedora uses
   `sudo dnf install python3`. No Python virtual environment is necessary.

3. Place the map archive at `maps/planet.pmtiles`:

   ```sh
   cp /path/to/planet.pmtiles maps/planet.pmtiles
   ```

   For a large archive on another disk, use a symbolic link instead:

   ```sh
   ln -s /opt/maps/planet.pmtiles maps/planet.pmtiles
   ```

   The account running the server must have read permission on the archive and
   execute/traverse permission on every parent directory. PMTiles files are
   ignored by Git because they are deployment data and can be very large.

4. Start the application from the repository root:

   ```sh
   python3 python-front.py
   ```

5. Open <http://127.0.0.1:8080/> in a browser.

The server streams byte ranges from the archive and does not load the complete
file into memory. MapLibre may cancel obsolete tile requests while navigating;
these normal disconnects are handled quietly.

## Command-line options

```text
--listen ADDRESS   Address to bind (default: 127.0.0.1)
--port PORT        TCP port (default: 8080)
--web-dir PATH     Frontend directory (default: ./web)
--map-dir PATH     Map archive directory (default: ./maps)
```

Paths supplied with `--web-dir` and `--map-dir` are resolved relative to the
current working directory. The bundled `maplibre-gl-js/` directory is located
relative to `python-front.py`.

To make the server reachable from other machines on a trusted network:

```sh
python3 python-front.py --listen 0.0.0.0 --port 8080
```

You may also need to allow TCP port 8080 through the host firewall. The built-in
server provides neither TLS nor authentication, so do not expose it directly to
the public Internet. Put a properly configured reverse proxy in front of it if
either feature is required.

## Optional systemd service

Adjust `User`, `WorkingDirectory`, and paths for the target machine:

```ini
[Unit]
Description=Situation map
After=network.target

[Service]
Type=simple
User=situation
WorkingDirectory=/opt/situation
ExecStart=/usr/bin/python3 /opt/situation/python-front.py --listen 127.0.0.1
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

Save this as `/etc/systemd/system/situation.service`, then run:

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now situation.service
sudo systemctl status situation.service
```

## HTTP endpoints

- `GET /` serves the application.
- `GET /health` returns plain text `OK`.
- `GET /api/status` returns JSON service status.
- `GET /maps/...` streams map assets with HTTP byte-range support.
- `GET /maplibre/...` serves the bundled MapLibre distribution.

Static-file requests reject URL traversal segments. Map files may be explicit
operator-managed symlinks so large archives can live on a separate filesystem.

## Verification

With the server running, use another terminal:

```sh
curl -i http://127.0.0.1:8080/
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/status
curl -H 'Range: bytes=0-126' -o /tmp/pmtiles-header \
  http://127.0.0.1:8080/maps/planet.pmtiles
```

Expected results are HTTP `200` for the application and API routes, body `OK`
from `/health`, and HTTP `206 Partial Content` for the map range request.

## Troubleshooting

- **The map archive could not be opened:** verify that `maps/planet.pmtiles`
  exists, its symlink target exists, and the server account can read it.
- **The page loads but the map is blank:** inspect the browser developer
  console and confirm WebGL is enabled. Also verify that the archive uses the
  Protomaps layer schema listed above.
- **Port already in use:** select another port with `--port`, or stop the process
  already listening on port 8080.
- **A glyph request returns 404:** the application bundles the primary Latin
  ranges only. Add the required `{range}.pbf` files beneath the matching
  `web/fonts/<font name>/` directory for additional writing systems.
- **`favicon.ico` returns 404:** no favicon is currently bundled; this browser
  request is harmless.
