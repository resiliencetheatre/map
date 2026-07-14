# TAK integration analysis

Copyright © 2026 Resilience Theatre. This project is licensed under GPLv3.
The project code is AI-generated and should be independently reviewed and
tested before operational use.

## Goal

Display live positions from ATAK Android devices in the MapLibre-based
`map` application.

## Planned architecture

ATAK devices
    -> taky-ng TAK server
    -> TAK bridge process/module
    -> python-front.py
    -> browser WebSocket
    -> MapLibre GeoJSON source

## Responsibilities

### taky-ng

- Accept ATAK client connections.
- Handle TAK TLS and client certificates.
- Receive and route CoT messages.
- Remain independent of the map application.

### TAK bridge

Prefer a separately structured Python component, initially runnable as its
own process.

The bridge should:

- connect to taky-ng as an ordinary TAK client;
- receive CoT events;
- parse and validate CoT;
- filter relevant position events;
- normalize TAK-specific data;
- track the newest event for each CoT UID;
- honor CoT `stale` timestamps;
- emit normalized JSON to python-front.py.

Avoid:

- directly importing undocumented taky-ng internals;
- polling the taky-ng database for live positions;
- exposing raw CoT directly to the browser;
- implementing a TAK server inside python-front.py.

## Preferred local interface

Use a Unix-domain stream socket with newline-delimited JSON.

Example path:

    /run/python-front/tak.sock

Example update:

    {"op":"upsert","track":{...}}

Example removal:

    {"op":"remove","id":"ANDROID-123"}

The bridge and python-front.py should reconnect cleanly if either process
is restarted.

## Normalized track model

Suggested fields:

- id
- source
- label
- latitude
- longitude
- altitude_m
- heading_deg
- speed_mps
- category
- cot_type
- event_time
- stale_time
- accuracy
- metadata

Example:

    {
      "op": "upsert",
      "track": {
        "id": "ANDROID-123",
        "source": "tak",
        "label": "Alpha-1",
        "latitude": 60.1,
        "longitude": 24.9,
        "altitude_m": 35,
        "heading_deg": 180,
        "speed_mps": 1.5,
        "category": "friendly-person",
        "cot_type": "a-f-G-U-C",
        "event_time": "2026-07-14T00:20:00Z",
        "stale_time": "2026-07-14T00:22:00Z"
      }
    }

## Track handling rules

- Use CoT `uid` as the stable identity.
- Ignore an event older than the currently stored event for the same UID.
- Validate latitude, longitude and timestamps.
- Remove or mark a track expired after its `stale` timestamp.
- Preserve the original CoT type.
- Do not assume all CoT events represent ATAK phone positions.
- Filter chat, routes, polygons, files and administrative events.
- Send a complete track snapshot when a browser first connects.
- Send incremental `upsert` and `remove` events afterwards.

## MapLibre side

Use a GeoJSON source rather than one DOM marker per device.

Possible properties:

- callsign
- category
- heading
- speed
- updated timestamp
- accuracy
- source
- CoT type

The browser must not parse raw CoT XML or manage TAK certificates.

## Security requirements

- Treat all CoT as untrusted input.
- Use safe XML parsing.
- Disable external XML entities.
- Limit event and metadata sizes.
- Bound queues.
- Validate coordinates.
- Escape callsigns and remarks before browser display.
- Keep the bridge interface local.
- Use TLS and client certificates between ATAK and taky-ng.

## Implementation sequence

1. Inspect the current python-front.py WebSocket and live-data architecture.
2. Inspect taky-ng's supported client interfaces.
3. Build a read-only CoT receiver connecting as a normal TAK client.
4. Capture representative ATAK position events.
5. Implement normalization and filtering.
6. Add the Unix-socket interface.
7. Add generic live-track support to python-front.py.
8. Add MapLibre GeoJSON display.
9. Test stale expiry, reconnects and malformed input.
10. Consider bidirectional TAK publishing only after reception is stable.

## Current scope

Analyze and design first. Do not implement until explicitly requested.
