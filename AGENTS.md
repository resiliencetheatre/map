## TAK integration

Before changing TAK-related code, read:

- `docs/tak-integration.md`

Keep TAK-specific protocol handling separate from the generic map and
WebSocket implementation.

Do not directly couple `python-front.py` to undocumented taky-ng internals.

Do not implement TAK-related changes unless the task explicitly requests
implementation. For analysis tasks, inspect the repository and propose a
plan without modifying files.

## Meshtastic integration

Before changing Meshtastic-related code, read:

- `docs/meshtastic-integration.md`

Keep Meshtastic serial, protocol, and PubSub handling in the standalone adapter.
Do not add the optional Meshtastic dependency to `python-front.py`.
