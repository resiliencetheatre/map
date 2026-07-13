## TAK integration

Before changing TAK-related code, read:

- `docs/tak-integration.md`

Keep TAK-specific protocol handling separate from the generic map and
WebSocket implementation.

Do not directly couple `python-front.py` to undocumented taky-ng internals.

Do not implement TAK-related changes unless the task explicitly requests
implementation. For analysis tasks, inspect the repository and propose a
plan without modifying files.
