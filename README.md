# Situation

![Situation map interface](docs/situation-map.excalidraw.png)

Copyright © 2026 Resilience Theatre.

The code in this repository is AI-generated. It should be independently
reviewed and tested before use in operational, safety-critical, or security-
sensitive environments.

Situation is a small, offline-capable situation-awareness web application. A
Python standard-library server delivers the user interface and a local PMTiles
world map to MapLibre GL JS. It does not require Flask, Django, Node.js, npm, a
database server, or a build step. Live and historical positions are stored in a
local SQLite database through Python's standard library.

![Situation map interface](docs/map.png)

## Requirements

### Server

- Linux or another operating system with Python 3.10 or newer
- Read access to a PMTiles v3 vector archive
- Enough free storage for the map archive (the archive is not included)
- `curl` is optional and is only needed for the verification commands below

Only Python standard-library modules are used, including `http.server`,
`sqlite3`, and `urllib.request`. There is no
`requirements.txt` because no Python packages need to be installed.

### Browser

- A current Firefox, Chromium, Chrome, or other MapLibre-compatible browser
- WebGL enabled, with working graphics drivers
- JavaScript enabled

Internet access is not required at runtime. Map data, JavaScript, CSS, fonts,
sprites, and the map style are all served locally.




## API usage

With `python-front.py` running on its default address, open the inline API
reference at [http://localhost:8080/api-usage](http://localhost:8080/api-usage).
It lists the HTTP endpoints, position-report schema, request examples, and
usage notes for `python-simulator.py` and `tak-bridge.py`.

The included simulator moves three civilian-response milsymbol demonstrations
near Luxembourg: civil protection, fire and rescue, and emergency medical
services. Each symbol shows its designation and the age of its latest report;
selecting it also shows speed and heading.

### Using military symbols

`web/index.html` loads `web/milsymbol.js` before the application module, making
the library available as `window.ms`. The backend position schema includes:

- `sidc`: a MIL-STD-2525/APP-6 Symbol Identification Code
- `designation`: example unit text rendered with the symbol
- `status_text`: optional free-form target status, up to 500 characters
- `latitude` and `longitude`: WGS84 decimal-degree coordinates

The frontend derives a target's age from the backend-generated `received_at`
timestamp (falling back to the device `timestamp`). Age is displayed in seconds
below one minute and as `minutes:seconds` thereafter, so it continues increasing
when a device stops reporting. The right-side target list separates targets into
Live and Idle tabs. The adjustable idle threshold defaults to 300 seconds and is
stored in browser local storage. Each target shows its last-known-good (LKG)
receipt time beside speed and heading; LKG is green for live targets and red for
idle targets. The selected tab also filters the map: Live shows only live
targets and their selected tails, while Idle shows only idle targets and their
selected tails. Map symbols retain their standard milsymbol colors in both
tabs.

For example:

```js
{"sidc":"E-O-B-----","designation":"Civil Protection Team","latitude":49.61,"longitude":6.13}
```

The frontend creates a canvas the first time it sees a `device_id`, then moves
the existing MapLibre marker for subsequent reports:

```js
const element = new window.ms.Symbol(position.sidc, {
  size: 32,
  uniqueDesignation: `${position.designation} · age ${formatAge(ageInSeconds(position))}`
}).asCanvas();

new maplibregl.Marker({ element, anchor: "center" })
  .setLngLat([position.longitude, position.latitude])
  .setPopup(popup)
  .addTo(map);
```

The browser polls `GET /api/positions` once per second. Markers are keyed by
`device_id`, so updates move symbols without creating duplicates. Consult the
milsymbol project for supported SIDCs and rendering options.

## Bundled web dependencies

| Component | Location | Purpose |
| --- | --- | --- |
| MapLibre GL JS `6.0.0` | `maplibre-gl-js/` | Interactive WebGL map renderer |
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
python-simulator.py         Three-device movement simulator
tak-bridge.py               Receive-only taky-ng position bridge
meshtastic-plugin.py        USB Meshtastic location/telemetry adapter
situation.db                Runtime SQLite position store (not committed)
web/                        Application HTML, CSS, JavaScript, and map assets
web/milsymbol.js            Bundled tactical-symbol renderer
web/report.html             Mobile browser position-reporting page
web/report-symbols.json     Symbols allowed by the reporting page
web/styles/situation.json   Active map style
maplibre-gl-js/             Bundled MapLibre ES modules and CSS
maps/planet.pmtiles         Required map archive or symlink (not committed)
web/map-layers.json         Base and regional PMTiles archive configuration
```

The application expects the vector archive to contain the Protomaps layers
`boundaries`, `buildings`, `earth`, `landcover`, `landuse`, `places`, `pois`,
`roads`, and `water`.

### Configuring map layers

Map sources are configured in `web/map-layers.json`. Exactly one archive has
the `base` role and remains visible everywhere. Regional archives use the
`overlay` role and automatically render above it only within their PMTiles
bounds and native zoom range. To add one, place it below `maps/` and add an
entry with a stable `id` and its `archive` filename:

```json
{
  "layers": [
    {
      "id": "planet",
      "archive": "planet.pmtiles",
      "role": "base"
    },
    {
      "id": "riyadh-governorate",
      "archive": "riyadh_governorate.pmtiles",
      "role": "overlay"
    }
  ]
}
```

Vector archives must use the Protomaps source-layer schema expected by
`web/styles/situation.json`. Raster PMTiles archives (PNG, JPEG, WebP, or AVIF)
are detected automatically and rendered as raster overlays. Reload the browser
after changing the config; the server does not need to be restarted.

### Browser position reporting

Open `/report` on a phone to submit its position to the Situation map. The page
requests high-accuracy browser geolocation on load and centers a crosshair on
the result. If access is unavailable or the position needs adjustment, pan and
zoom the map until the crosshair is over the desired location. The form shows
the selected latitude, longitude, and zoom and accepts an editable target name
and optional status text.

Each browser receives a random device ID stored in local storage. Its editable
target name is stored there as well, so later reports update the same target.
Clearing site storage creates a new identity. Browser geolocation normally
requires HTTPS, except when accessing the application through localhost.

Select **Report Position** to append the selected coordinate to the position
store. Reports from this page use the same API as hardware adapters and the
simulator; status is optional, so existing clients remain compatible.

The symbol selector is populated from `web/report-symbols.json`. Each entry
contains a `sidc`, user-facing `label`, and optional `group` used to organize
the dropdown. Edit this file to control which civilian or military symbols a
reporting user may select, then reload `/report`. The selected SIDC is stored in
browser local storage and sent with every report; changing it causes the main
map to redraw that target with the new symbol.

Browser and adapter reports may include an optional `status_text` string of up
to 500 characters. Non-empty status text appears below the target in Activity
and in its map popup. The simulator submits `simulation` for this field.

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

4. Configure local HTTPS as described in [Local HTTPS with Caddy](#local-https-with-caddy).
   HTTPS is required for browser geolocation on phones.

5. Start Caddy first, from the repository root, and leave it running:

   ```sh
   caddy run --config ./Caddyfile.test
   ```

6. In a second terminal, start the Python application. Keep it bound to
   loopback because Caddy is the network-facing process:

   ```sh
   python3 python-front.py
   ```

7. Open `https://situation.local:8443/` in a browser. Replace
   `situation.local` with the hostname entered in the certificate configuration.
   The phone must resolve that name to the server and trust the local CA as
   described below.

8. In a third terminal, start the simulator:

   ```sh
   python3 python-simulator.py
   ```

   The three symbols should appear and move once per second. Stop the simulator
   with `Ctrl+C`; all submitted points remain in `situation.db`.

## Local HTTPS with Caddy

The reporting page needs browser geolocation, which normally requires HTTPS on
a phone. `Caddyfile.test` terminates HTTPS on TCP port 8443 and proxies requests
to the Python server on `127.0.0.1:8080`. The included test certificates are for
local development only. Never distribute a CA private key or reuse this test CA
for other purposes.

### Install Caddy and OpenSSL on Debian

Install the stable Caddy package from its
[official Debian repository](https://caddyserver.com/docs/install#debian-ubuntu-raspbian):

```sh
sudo apt update
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl openssl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo chmod o+r /usr/share/keyrings/caddy-stable-archive-keyring.gpg
sudo chmod o+r /etc/apt/sources.list.d/caddy-stable.list
sudo apt update
sudo apt install caddy
```

The package starts a system-wide `caddy` service automatically. This repository
uses a foreground Caddy process and its local configuration, so stop the package
service to avoid an admin-port conflict:

```sh
sudo systemctl disable --now caddy
caddy version
```

### Create a certificate for a new hostname

Choose the exact hostname phones will use, such as `situation.local`, and make
sure it resolves to the server's LAN address through local DNS, mDNS, or a DNS
entry on the router. Opening the service by IP address requires that IP address
to be present in the certificate too.

Edit `caddy/server-certificates.cnf`. Replace `situation.local` under
`[subject_alt_names]` with the new hostname and replace or add `IP.n` entries
for every LAN address clients may use. Keep the `DNS.n` and `IP.n` numbering
unique and consecutive, for example:

```ini
[subject_alt_names]
DNS.1 = localhost
DNS.2 = map.example.internal
IP.1 = 127.0.0.1
IP.2 = 192.168.1.50
```

Create a local CA once. Preserve its private key securely; only the `.crt`
public certificate is copied to client devices:

```sh
mkdir -p caddy/certs
chmod 700 caddy/certs
openssl genrsa -out caddy/certs/situation-test-ca.key 3072
openssl req -x509 -new -sha256 -days 3650 \
  -key caddy/certs/situation-test-ca.key \
  -out caddy/certs/situation-test-ca.crt \
  -subj '/CN=Situation Test CA/O=Situation Local Testing'
```

Generate a new server key and certificate after every hostname or IP change:

```sh
openssl genrsa -out caddy/certs/situation-server.key 2048
openssl req -new -sha256 \
  -key caddy/certs/situation-server.key \
  -out /tmp/situation-server.csr \
  -config caddy/server-certificates.cnf
openssl x509 -req -sha256 -days 365 \
  -in /tmp/situation-server.csr \
  -CA caddy/certs/situation-test-ca.crt \
  -CAkey caddy/certs/situation-test-ca.key \
  -CAcreateserial \
  -out caddy/certs/situation-server.crt \
  -extfile caddy/server-certificates.cnf \
  -extensions server_certificate
chmod 600 caddy/certs/*.key
rm /tmp/situation-server.csr
```

The private keys and CA serial file are ignored by Git. Verify the SAN list and
Caddy configuration before starting either server:

```sh
openssl x509 -in caddy/certs/situation-server.crt -noout -subject -dates -ext subjectAltName
caddy validate --config ./Caddyfile.test
```

Run Caddy first and leave it in the foreground:

```sh
caddy run --config ./Caddyfile.test
```

Then run `python3 python-front.py` in another terminal. Caddy may initially log
`502 Bad Gateway` until Python starts; this is expected. Browse to the hostname
in the certificate, including the configured port, for example
`https://map.example.internal:8443/`. Do not use the HTTP backend URL from a
phone.

### Open the Debian firewall with UFW

Only Caddy's HTTPS port needs to accept LAN traffic; Python remains on loopback.
If the server is administered through SSH, allow SSH before enabling UFW so the
current session is not locked out:

```sh
sudo apt update
sudo apt install ufw
sudo ufw allow OpenSSH
sudo ufw allow 8443/tcp comment 'Situation HTTPS'
sudo ufw enable
sudo ufw status verbose
```

Omit the `OpenSSH` rule when SSH is not installed. Restrict the HTTPS rule to a
trusted subnet when possible, for example:

```sh
sudo ufw delete allow 8443/tcp
sudo ufw allow from 192.168.1.0/24 to any port 8443 proto tcp comment 'Situation LAN HTTPS'
```

Do not open port 8080 while Python uses its default `127.0.0.1` binding. If the
Caddyfile is changed to standard HTTPS, allow `443/tcp` instead of `8443/tcp`.

### Trust the CA on an iPhone or iPad

Transfer only `caddy/certs/situation-test-ca.crt` to the device using a trusted
method such as AirDrop, Mail, or a temporary authenticated file share. Never
transfer either `.key` file.

1. Open the `.crt` file and allow the configuration profile to download.
2. Open **Settings > General > VPN & Device Management**, select the downloaded
   profile, tap **Install**, and follow the prompts.
3. Open **Settings > General > About > Certificate Trust Settings** and enable
   full trust for **Situation Test CA**. Manually installed roots are not trusted
   for TLS until this separate switch is enabled, as described by
   [Apple Support](https://support.apple.com/en-gb/102390).
4. In Safari, open the HTTPS URL whose hostname exactly matches a DNS SAN in the
   server certificate.

Remove the profile after testing from **Settings > General > VPN & Device
Management**. For managed devices, deploy the public CA certificate with Apple
Configurator or MDM instead of asking every user to install it manually.

### Trust the CA on Android

Copy only `caddy/certs/situation-test-ca.crt` to the device. On current Pixel
devices, open **Settings > Security & privacy > More security settings >
Encryption & credentials > Install a certificate > CA certificate**, select
the file, acknowledge the warning, and name the certificate. A screen lock may
be required. Other manufacturers may label or move these menus; search Settings
for **Install certificate** or **CA certificate**. See Google's
[certificate installation guidance](https://support.google.com/pixelphone/answer/2844832?hl=en)
for the current credential-settings path.

Open the matching HTTPS URL in Chrome. If Chrome still rejects the certificate,
confirm that the CA was installed as a **CA certificate**, not a Wi-Fi or VPN
client certificate, and that the URL hostname or IP appears in the server
certificate's SAN list. Some managed Android devices prohibit user-added CAs;
their administrator must deploy the CA policy. Remove it after testing from
**Encryption & credentials > User credentials** (wording varies by device).

## TAK bridge (initial receive-only version)

`tak-bridge.py` makes live Cursor on Target (CoT) positions received by
[taky-ng](https://codeberg.org/hunterSG7/taky-ng) available to Situation. It is
a separate receive-only process and connects to taky-ng as an ordinary TAK
client; it does not import taky-ng code or read its database.

The initial data path is:

```text
ATAK -> taky-ng TCP listener -> tak-bridge.py -> POST /api/positions
     -> python-front.py -> browser polling -> Live/Idle map targets
```

### Prerequisites and startup

- Run taky-ng with its plain CoT TCP listener enabled on port 8087.
- Connect at least one ATAK or other CoT-producing client to taky-ng.
- Run Python 3.10 or newer; the bridge has no third-party dependencies.
- Keep plain TCP on localhost or a trusted private network because it provides
  neither encryption nor client authentication.

Start `python-front.py` first, then run the bridge in a second terminal from the
repository root:

```sh
python3 python-front.py
python3 tak-bridge.py
```

By default, `tak-bridge.py` connects as an ordinary TAK client to the unencrypted
TCP listener at `127.0.0.1:8087` and posts received positions to
`http://127.0.0.1:8080/api/positions`. An ATAK client's current position then
appears in the Live target list and on the map. It moves to Idle according to
the browser's configured idle threshold if reports stop arriving.

To confirm reception, watch for messages such as:

```text
Connected to TAK server at 127.0.0.1:8087
Updated ALPHA 1 (ANDROID-deadbeef)
```

### Connection options

To connect to a different host or Situation API:

```sh
python3 tak-bridge.py --host 192.0.2.10 --port 8087 \
  --url http://127.0.0.1:8080/api/positions
```

Available options are:

```text
--host HOST                 taky-ng host (default: 127.0.0.1)
--port PORT                 Plain CoT TCP port (default: 8087)
--url URL                   Situation API URL
--reconnect-delay SECONDS   Delay after a lost TAK connection (default: 3)
--max-event-bytes BYTES     Maximum accepted CoT event size (default: 1048576)
--event-log MODE            quiet, summary, or raw (default: summary)
```

The bridge reconnects automatically when taky-ng restarts. If Situation is not
running, it logs `Cannot post ... Connection refused` but remains connected to
taky-ng and tries again when the next position arrives. If taky-ng is not
running or its listener is bound to another interface, it logs a connection
error and retries after the configured delay.

### Observing TAK events

The default `--event-log summary` mode emits one JSON-formatted `CoT` line for
every received event, including events that the initial position bridge does
not forward. Each line records the event type, UID, `how`, timestamps, whether
it has a point, nested detail element names, the action taken, and the reason.
For example, an unsupported data type may appear as:

```text
CoT {"action":"ignored","reason":"non-atom event type","type":"b-t-f","uid":"...","how":"...","time":"...","stale":"...","has_point":true,"detail_types":["__chat","chatgrp"]}
```

This summary is intended to identify chat, mission, route, sensor, file, and
other CoT families before adding support for them. Use quiet mode to retain
only connection, forwarding, and error messages:

```sh
python3 tak-bridge.py --event-log quiet
```

For short diagnostic captures, raw mode also writes each event's serialized
XML, limited to 4096 characters per event:

```sh
python3 tak-bridge.py --event-log raw
```

Raw CoT can contain callsigns, locations, chat text, mission identifiers, and
other sensitive operational data. Do not leave raw logging enabled routinely,
and protect or delete captured terminal and service logs appropriately. Raw
logging does not change the event-size validation or forward raw CoT to the
browser or Situation API.

### CoT handling

The bridge accepts current CoT atom (`a-...`) point events and ignores chat,
routes, files, and administrative messages. It validates coordinates and CoT
timestamps, rejects events after their `stale` time, ignores older updates for
the same UID, limits event and identity sizes, and rejects XML DTD/entity
declarations.

Fields are mapped as follows:

| CoT field | Situation field |
| --- | --- |
| Event `uid` | Stable `device_id` |
| Event `time` | Position timestamp |
| Point `lat`, `lon`, `ce` | Coordinates and accuracy |
| Contact `callsign` | Designation, falling back to UID |
| Track `course` | Heading in degrees |
| Track `speed` | Speed converted from m/s to km/h |
| Type affiliation | Basic friendly, hostile, neutral, or unknown unit SIDC |

TAK's `9999999` unknown-accuracy sentinel is stored as zero rather than as a
misleading accuracy measurement.

### Current limitations

This first version does not connect to TAK TLS port 8089 with client
certificates, send data back to TAK, or remove an already stored Situation
position exactly when its CoT `stale` timestamp passes. It also uses the
existing HTTP position API rather than the planned generic live-track registry
and Unix-domain socket. These are intended follow-up additions after basic
reception is stable.

Run `python3 tak-bridge.py --help` for all connection and safety-limit options.

## Meshtastic plugin

`meshtastic-plugin.py` is a receive-only adapter for a Meshtastic radio attached
over USB serial. It keeps Meshtastic-specific handling outside
`python-front.py`: the adapter reads the Python client's node database,
normalizes located nodes, and posts them to the existing Situation position
API. This also imports nodes already known by the attached radio, not only
packets received after the adapter starts.

The adapter design is documented in
[`docs/meshtastic-integration.md`](docs/meshtastic-integration.md). The supplied
`meshtastic/meshpipe_ng.py` example was reviewed before implementation and was
useful for identifying practical location and telemetry fields. Its historical
source is the Resilience Theatre
[`rpi-extree`](https://git.resilience-theatre.com/resiliencetheatre/rpi-extree)
repository. The example was then removed: the new adapter uses Situation's HTTP
API and the Meshtastic client's merged node database instead of carrying over
the example's FIFOs, private SQLite database, GPS threads, or outbound-message
behavior.

The main server remains dependency-free. On Debian and Ubuntu, install the
virtual-environment support package if it is not already present, then create a
project-local environment for the optional radio library:

```sh
sudo apt install python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install meshtastic
```

Start Situation, then start the adapter. Omit `--port` to let the Meshtastic
library auto-detect a supported serial device:

```sh
python3 python-front.py
.venv/bin/python meshtastic-plugin.py --port /dev/ttyACM0
```

Each node with a valid WGS84 position appears as a separate map target. Its
Meshtastic long name is used as the designation. Available battery percentage,
voltage, hardware model, SNR, RSSI, hop count, altitude, satellite/PDOP data,
channel utilization, and airtime utilization are shown in the target status.
Missing fields are simply omitted; nodes without a valid position are not
posted. Position packets can be less precise when a node is configured to limit
location precision.

The adapter reacts to node-database update events and also performs a full scan
every 30 seconds. It only posts a node when its location or displayed metadata
has changed. Useful options are:

```text
--port DEVICE             USB serial device (default: auto-detect)
--url URL                 Position API (default: http://127.0.0.1:8080/api/positions)
--interval SECONDS        Full node scan interval (default: 30)
--reconnect-delay SECONDS Delay after radio disconnect (default: 3)
```

Only one process can normally own a serial port at a time. Stop the Meshtastic
CLI, `meshpipe_ng.py`, or another serial client before starting the adapter.
The adapter reads location and telemetry but does not transmit messages or
change radio configuration.

## Simulator

The simulator creates a UUID track session and posts three positions per update
to `POST /api/positions`. It runs continuously by default.

```text
--url URL           Position API (default: http://127.0.0.1:8080/api/positions)
--interval SECONDS  Delay between updates; minimum 0.1 (default: 1.0)
--steps COUNT       Stop after COUNT updates; 0 runs forever (default: 0)
--run-id ID         Use a specific track session ID instead of a UUID
```

For a short ten-update test:

```sh
python3 python-simulator.py --steps 10 --interval 0.1
```

Each report includes a run ID, device ID, timestamp, coordinates, heading,
speed, accuracy, SIDC, and designation. This is the contract that a future
hardware adapter can use in place of the simulator.

Example request body:

```json
{
  "run_id": "exercise-001",
  "device_id": "alpha-1",
  "timestamp": "2026-07-12T05:00:00Z",
  "latitude": 49.6116,
  "longitude": 6.1319,
  "heading": 120,
  "speed": 8.0,
  "accuracy": 5.0,
  "sidc": "SFGPUCI----K---",
  "designation": "ALPHA 1",
  "status_text": "Awaiting instructions"
}
```

Coordinates use WGS84 decimal degrees, heading is degrees clockwise from north,
speed is kilometres per hour, and accuracy is metres. `status_text` is optional;
omitting it or sending an empty string hides the status line in Activity.

## Position database

`python-front.py` creates `situation.db` automatically. The append-only
`positions` table stores both device timestamps and backend receipt timestamps.
Indexes support retrieval by simulation run and latest device position. The
database and its SQLite sidecar files are excluded from Git.

Use `--database PATH` to place it elsewhere. SQLite manages concurrent request
threads through short, independent connections; no external database service
or administration is required.

The server streams byte ranges from the archive and does not load the complete
file into memory. MapLibre may cancel obsolete tile requests while navigating;
these normal disconnects are handled quietly.

## Command-line options

```text
--listen ADDRESS   Address to bind (default: 127.0.0.1)
--port PORT        TCP port (default: 8080)
--web-dir PATH     Frontend directory (default: ./web)
--map-dir PATH     Map archive directory (default: ./maps)
--database PATH    SQLite position database (default: ./situation.db)
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
- `GET /report` serves the mobile browser position-reporting page.
- `GET /health` returns plain text `OK`.
- `GET /api/status` returns JSON service status.
- `POST /api/positions` validates and stores one position report.
- `GET /api/positions` returns the latest report for each device.
- `GET /api/positions/tails?seconds=<5-300>` returns recent tail points.
- `GET /api/tracks` lists recorded simulation sessions.
- `GET /api/tracks/<run_id>` returns every point in a recorded session.
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

## License

Situation is free software licensed under the GNU General Public License,
version 3. See [LICENSE](LICENSE) for the complete license text.

Copyright © 2026 Resilience Theatre.

The code in this repository is AI-generated. No warranty is provided; review
and test it for your intended use. Bundled third-party dependencies and assets
remain subject to their respective licenses described above.
