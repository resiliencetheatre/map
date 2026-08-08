# Meshtastic integration

Copyright © 2026 Resilience Theatre. This project is licensed under GPLv3.
The project code is AI-generated and should be independently reviewed and
tested before operational use.

## Goal

Display the last known locations and useful radio metadata for the USB-attached
Meshtastic node and the other nodes known to it.

## Architecture

```text
Meshtastic mesh
    -> USB-attached radio
    -> Meshtastic Python client node database
    -> meshtastic-plugin.py
    -> POST /api/positions
    -> Situation SQLite position store
    -> browser polling
    -> MapLibre markers
```

`meshtastic-plugin.py` is a separately runnable adapter. Meshtastic protocol,
serial, protobuf, and PubSub handling must remain outside `python-front.py` and
the browser. The generic Situation position API is the integration boundary.

## Design principles

### Keep dependencies optional

The Situation server uses only the Python standard library. The Meshtastic
package and its transitive dependencies belong in the project-local virtual
environment used for the adapter; they must not become imports of
`python-front.py`.

### Use the public client API

Use `meshtastic.serial_interface.SerialInterface`, the read-only `nodesByNum`
node database, and documented PubSub events. Do not couple the adapter to
private Meshtastic methods or protobuf implementation details when normalized
dictionary fields are available.

Current releases publish both `node` and `interface` on
`meshtastic.node.updated`. Callback signatures must explicitly accept both
names because PyPubSub may infer the topic schema from the first listener.

### Treat the node database as authoritative

The client maintains merged user, position, link, and telemetry information.
Read complete entries from `nodesByNum` instead of recursively interpreting
each packet. This provides an initial snapshot of nodes already known to the
radio and avoids losing metadata when position and telemetry arrive in
different packets.

Node updates wake the adapter immediately. A periodic full scan provides a
simple recovery path if a library version does not publish an expected event.
Unchanged normalized reports are not posted again.

### Normalize at the adapter boundary

The adapter maps radio data into the existing Situation contract:

| Meshtastic value | Situation value |
| --- | --- |
| User ID or numeric node ID | Stable `device_id` prefixed with `meshtastic:` |
| Long name, short name, or node ID | `designation` |
| Position latitude/longitude | WGS84 coordinates |
| Position time or last-heard time | `timestamp` |
| Last-heard time, when known | Optional `activity_at` liveness reference |
| Ground track | Heading in degrees |
| Ground speed in m/s | Speed in km/h |
| Radio and device telemetry | Bounded `status_text` |

Battery and voltage come from `deviceMetrics`, not from `position`. Optional
metadata includes hardware model, SNR, RSSI, hop count, altitude, satellites,
PDOP, channel utilization, and airtime utilization. Missing metadata is
omitted. Nodes without a valid position are not submitted.

Situation normally measures target age from the time it receives a report.
Meshtastic nodes may already be old when their cached entries are first read,
so the adapter also sends `lastHeard` as `activity_at`. The map prefers this
optional source-observation time for age, LKG display, and Live/Idle
classification while retaining `received_at` as the import time. If
`lastHeard` is unavailable, the normal receipt-time behavior remains in force.

These timestamps intentionally describe different events:

- `timestamp` is the time associated with the stored position fix;
- `activity_at` is the latest time the attached radio heard that mesh node;
- `received_at` is generated when Situation accepts the normalized report.

The API validates `activity_at` as a timezone-aware ISO 8601 value and
normalizes it to UTC. Existing databases gain a nullable `activity_at` column
at server startup. This preserves old records and keeps adapters that do not
provide source activity information backward-compatible.

### Remain receive-only by default

The adapter must not send mesh messages, request remote configuration changes,
or change radio settings merely to display nodes. Any future transmit feature
needs an explicit operator-facing design and separate authorization.

### Handle operational failure cleanly

- Validate coordinates and numeric values before submission.
- Bound displayed metadata to the position API limit.
- Keep the last successfully submitted fingerprint per node.
- Retry failed HTTP submissions on the next scan or update.
- Close and reopen the serial interface after connection loss.
- Allow only one process to own the serial device.
- Never expose raw packets, keys, or channel configuration through the map API.

## Relationship to the removed example

The manually supplied `meshtastic/meshpipe_ng.py` was reviewed before this
adapter was implemented. It was useful for confirming practical node-database
fields such as user identity, position, battery, SNR/RSSI, hop information,
satellites, and PDOP.

For historical provenance, the example originated in the Resilience Theatre
`rpi-extree` repository:

- <https://git.resilience-theatre.com/resiliencetheatre/rpi-extree>

The new adapter deliberately does not retain the example's FIFO protocol,
recursive packet decoding, `/tmp/radio.db`, GPS-file threads, outbound text
messaging, global state, or forceful process exits. Situation already has a
validated HTTP position contract and SQLite store, while the Meshtastic Python
client already maintains a merged node database. Reusing those two boundaries
produces a smaller receive-only module with fewer synchronization and recovery
paths.

The example directory was removed after the relevant behavior was documented;
it is not a runtime dependency or vendored source for the adapter.

## Testing boundaries

Automated tests should cover normalization without requiring Meshtastic to be
installed or a radio to be attached. A live test should additionally verify:

1. initial forwarding of located nodes already in the radio database;
2. position movement after a received position packet;
3. status changes after device telemetry;
4. operation when optional fields are absent;
5. serial disconnect and reconnect;
6. no repeated posts when the normalized node entry is unchanged.
