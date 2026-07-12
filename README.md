# Situation

A minimal, dependency-free situation-awareness web application. It provides a
static frontend, a reserved map-asset namespace, and lightweight health/status
endpoints using only the Python 3 standard library.

## Run

```sh
python3 python-front.py
```

Then open <http://127.0.0.1:8080/>.

Available options:

```text
--listen ADDRESS   Bind address (default: 127.0.0.1)
--port PORT        TCP port (default: 8080)
--web-dir PATH     Frontend directory (default: ./web)
--map-dir PATH     Map asset directory (default: ./maps)
```

Frontend files are served from `/`; files placed in `./maps/` are available
under `/maps/`. The server rejects paths that resolve outside either configured
directory. The world map uses the local MapLibre GL JS distribution and
`maps/planet.pmtiles`; large archive responses are streamed with HTTP byte-range
support. `web/pmtiles.js` is the browser protocol adapter used by MapLibre.
The project-specific `web/styles/situation.json` is adapted from EdgeUI's bright
style. Its filters use current expression syntax, and unavailable satellite and
terrain sources are omitted. The original downloaded style is retained only as
source material.
The Latin regular and italic glyph ranges used for primary labels are bundled
under `web/fonts/`; MapLibre falls back gracefully for unavailable ranges.

## Endpoints

- `GET /health` returns `OK` as plain text.
- `GET /api/status` returns the service state as JSON.
