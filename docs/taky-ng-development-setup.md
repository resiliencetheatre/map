# taky-ng Development Setup

This document describes a practical development setup for running
[`taky-ng`](https://codeberg.org/hunterSG7/taky-ng) alongside the `map`
project.

The recommended approach is to keep `taky-ng` as a separate sibling Git
repository with its own Python virtual environment. Do not install it into the
same virtual environment as `python-front.py`, and do not copy it into the
`map` repository.

## Recommended directory layout

```text
~/laboratory/
├── map/
│   ├── python-front.py
│   └── docs/
├── taky-ng/
│   ├── .git/
│   ├── .venv/
│   ├── pyproject.toml
│   ├── taky/
│   └── taky.conf.sample
└── taky-runtime/
    ├── taky-dev.conf
    ├── certs/
    ├── logs/
    └── data/
```

Keep runtime configuration, generated certificates, databases and logs outside
the upstream `taky-ng` checkout.

## Clone the repository

```bash
cd ~/laboratory
git clone https://codeberg.org/hunterSG7/taky-ng.git
cd taky-ng
```

## Create the virtual environment

On Debian 13, install the required Python tools if necessary:

```bash
sudo apt install python3-venv python3-pip
```

Create and activate the environment:

```bash
cd ~/laboratory/taky-ng
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade the packaging tools:

```bash
python -m pip install --upgrade pip setuptools wheel
```

## Install taky-ng in editable mode

The project uses `pyproject.toml` with setuptools and defines the package name
`taky-ng`.

Install the checkout in editable mode:

```bash
python -m pip install -e .
```

Editable mode means changes made in the source checkout are used immediately
without reinstalling the package.

To install the optional development tools declared in `pyproject.toml`:

```bash
python -m pip install -e '.[dev]'
```

The optional `dev` extra currently includes tools such as:

- `tox`
- `black`
- `pre-commit`
- `pylint`

The repository also declares a separate development dependency group containing
`pytest`, `pytest-cov` and `coverage`. With ordinary pip, these can be installed
directly:

```bash
python -m pip install pytest pytest-cov coverage
```

If using `uv`, the project also contains `uv.lock`, and the dependency group can
be installed with:

```bash
uv sync --group dev
```

## Installed commands

The current `pyproject.toml` defines these console commands:

```text
taky       CoT server and router
taky_dps   TAK data-package service
takyctl    Administration and control utility
```

Verify the installed commands:

```bash
command -v taky taky_dps takyctl
```

They should resolve inside the virtual environment, for example:

```text
/home/tech/laboratory/taky-ng/.venv/bin/taky
```

Inspect their command-line options:

```bash
taky --help
taky_dps --help
takyctl --help
```

For the first position-reception tests, the main service of interest is normally
`taky`. The data-package service is not necessarily required merely to receive
ATAK CoT position messages.

## Verify the editable installation

Check the installed package metadata:

```bash
python -m pip show taky-ng
python -m pip check
```

Confirm that Python imports the package from the source checkout:

```bash
python - <<'PY'
import taky
print(taky.__file__)
PY
```

The printed path should point into:

```text
~/laboratory/taky-ng/taky/
```

## Prepare a development configuration

The repository includes:

```text
taky.conf
taky.conf.sample
```

Keep the sample file unchanged and create a separate runtime configuration:

```bash
mkdir -p ~/laboratory/taky-runtime
cp ~/laboratory/taky-ng/taky.conf.sample \
   ~/laboratory/taky-runtime/taky-dev.conf
```

Edit the development copy:

```bash
nano ~/laboratory/taky-runtime/taky-dev.conf
```

Before changing it, inspect the supplied documentation and configuration:

```bash
sed -n '1,260p' README.md
sed -n '1,260p' doc/README_QUICKSTART.md
sed -n '1,260p' taky.conf.sample
cat Makefile
```

Also compare the two included configuration files:

```bash
diff -u taky.conf.sample taky.conf || true
```

Use the exact configuration option shown by `taky --help`. Do not assume the
option is named `--config` without confirming it from the installed version.

A typical command may eventually resemble:

```bash
~/laboratory/taky-ng/.venv/bin/taky \
    --config ~/laboratory/taky-runtime/taky-dev.conf
```

The actual syntax must match the current `taky --help` output.

## Redis

`taky-ng` declares the Python Redis client as a dependency. Some or all server
components may require a running Redis service.

Install Redis on Debian:

```bash
sudo apt install redis-server
sudo systemctl enable --now redis-server
```

Verify it:

```bash
redis-cli ping
```

Expected output:

```text
PONG
```

Confirm from the current configuration and source whether the basic `taky` CoT
router requires Redis, or whether Redis is only needed by the DPS or
administrative components.

## Run tests

With the development dependencies installed:

```bash
cd ~/laboratory/taky-ng
source .venv/bin/activate
pytest -v
```

The Makefile may also provide project-specific test or lint targets:

```bash
cat Makefile
```

To inspect a target without running it:

```bash
make -n test
```

## Development launcher

After confirming the exact startup syntax, create a launcher outside the
`taky-ng` repository:

```bash
nano ~/laboratory/run-taky-dev.sh
```

Example skeleton:

```sh
#!/bin/sh
set -eu

TAKY_DIR="$HOME/laboratory/taky-ng"
CONFIG="$HOME/laboratory/taky-runtime/taky-dev.conf"

cd "$TAKY_DIR"
exec "$TAKY_DIR/.venv/bin/taky" --config "$CONFIG"
```

Replace `--config` if the current command uses another option.

Make the launcher executable:

```bash
chmod +x ~/laboratory/run-taky-dev.sh
```

## Source-control precautions

Do not commit generated runtime material or private keys.

Useful ignore patterns include:

```gitignore
.venv/
runtime/
certs/
*.pem
*.key
*.p12
*.pfx
*.db
*.sqlite
*.log
```

Record the exact upstream revision used for integration testing:

```bash
cd ~/laboratory/taky-ng
git rev-parse HEAD
git describe --always --dirty
```

Add the tested commit hash to the `map` project documentation so future changes
can be reproduced.

## Integration boundary for the map project

The intended development architecture is:

```text
ATAK phones
    -> taky-ng
    -> separate TAK bridge process
    -> python-front.py
    -> browser WebSocket
    -> MapLibre
```

Recommended rules:

- Treat the upstream `taky-ng` checkout as read-only unless explicitly creating
  a fork.
- Do not import undocumented `taky-ng` internals directly into
  `python-front.py`.
- Prefer making the bridge connect to `taky-ng` as a normal TAK client.
- Keep TAK protocol parsing and normalization outside the browser.
- Keep `taky-ng`, the bridge and `python-front.py` independently restartable.
- Use separate virtual environments for `taky-ng` and the `map` project.

For initial development, run the services in separate terminals rather than
adding systemd units or containers immediately. Once the integration is stable,
the components can be packaged as separate services.
