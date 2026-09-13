<p align="center">
    <img src="https://raw.githubusercontent.com/bemunin/isaac-powerpack/main/docs/public/logo.svg" width="400"/>
</p>

**Isaac Powerpack** (or **Pow** for short) is a project management tool that aims to reduce friction in **NVIDIA Isaac Sim** application development.


Key features:

* ⚡ CLI to simplify Isaac Sim workstation installation, setup, and launching.
* 📁 Provides an organized folder structure to help you get started.
* 📦 Keeps your Isaac Sim projects isolated from each other.
* 🛠️ Allows for configuring different Isaac Sim runtime settings via profiles.
* 🐢 Simple commands for building and running Isaac Sim ROS 2 Docker containers.
* 🎨 Local asset management and USDA linting tools.

Support platforms:

| Platform              | Version / Notes              |
| :-------------------- | :--------------------------- |
| OS                    | Ubuntu 22.04 / 24.04         |
| ROS 2 Docker          | Jazzy                        |
| Isaac Sim             | `6.1.0` (default), `5.1.0`   |

For the full list of ready-to-use commands and options, see the [CLI Reference](docs/cli-reference.md).

> [!NOTE]
> Pow CLI is actively evolving. New releases may introduce changes to commands, configuration options, or APIs. See the [Changelog](packages/pow-cli/CHANGELOG.md) for the latest updates.


## Installation

Pow CLI requires [uv](https://docs.astral.sh/uv/) and [Docker](https://docs.docker.com/get-docker/) (for ROS 2 container support). Ensure both are installed before proceeding:


Install `pow` as a user-level tool:

```bash
# install the latest pow CLI as a user-level tool
uv tool install pow-cli

# add uv's tool directory to your PATH (once, then restart your shell)
uv tool update-shell
```

`pow` is now available everywhere — for example:

```bash
# Run Isaac Sim from any directory
pow sim

# or run the compatibility checker to verify the machine meets Isaac Sim's requirements
pow sim check
```

If you have already installed `pow`, upgrade it with:

```bash
# show the installed version
uv tool list

# move to the latest release
uv tool upgrade pow-cli
```

To uninstall it from your system:
```bash
uv tool uninstall pow-cli
```

## Usage

Initialize a project:
```bash
# create your project folder
mkdir your-project && cd your-project

# create pyproject.toml and initialize uv
uv init --bare

# Initialize the project, install Isaac Sim, set up ROS, and create the config file
pow init

# Or select the Isaac Sim version without the interactive picker
pow init --sim-version 6.1.0
```

Check the installed Pow CLI version:

```bash
pow --version
# or
pow -v
```

Run Isaac Sim:

```bash
# Run the current project's configured Isaac Sim version
pow run

# Run Isaac Sim from any directory. This uses [sim] default_version from
# ~/.pow/system.toml, or the newest installed version when it is unset.
pow sim


# Run a standalone Python application with Isaac Sim's Python
pow python path/to/python_standalone_app.py
```

Run a ROS 2 container:

```bash
# Get into the ROS container. Later runs attach to the same container.
pow ros

# Build or rebuild the custom ROS image configured by ros_dockerfile in pow.toml
pow ros build

# Rebuild the custom image entirely without Docker's layer cache
pow ros build --no-cache

```


## Profiles

After running `pow init`, a `pow.toml` configuration file is generated in your project root. This file controls Isaac Sim runtime settings and supports multiple profiles, letting you switch between them depending on your use case:

```bash
pow run -p perf        # Use the "perf" profile
pow run -p default     # Use the default profile (or just `pow run`)
```

Each profile can extend another and override specific settings such as `cpu_performance_mode` or `headless`. To extend a list instead of replacing it, use the `.add` suffix (e.g. `exts.add`, `raw_args.add`).

In the example below, the `"perf"` profile extends `"default"`, enables CPU performance mode, and appends to `raw_args` using `raw_args.add`. Note that `exts` (without `.add`) replaces the inherited value entirely.

```toml
[sim]
version = "6.1.0"
ext_folders = ["./exts"]
cpu_performance_mode = false
headless = false
enable_ros = false
ros_bridge = "jazzy"
isaacsim_ros_ws = "~/IsaacSim-ros_workspaces"
ros_dockerfile = ""
ros_docker_image = "pow_simros"
exts = ["isaacsim.code_editor.vscode"]
raw_args = ["--/renderer/raytracingMotion/enabled=false"]

[[profiles]]
name = "perf"
extends = "default"
cpu_performance_mode = true
exts = ["your.custom.extension"]
raw_args.add = [
    # Enable frame generation 2x (RTX 50 series only)
    "--/rtx-transient/dlssg/enabled=true",
    "--/rtx-transient/internal/dlssg/interpolatedFrameCount=1",
    # Disable RTX features for better performance
    "--/rtx/reflections/enabled=false",
    "--/rtx/translucency/enabled=false"
]
```

For the full settings reference, profile inheritance, and examples, see the [Configuration Guide](docs/configuration.md).

## Asset Management

Local assets let you download predefined asset collections from NVIDIA Omniverse in advance. Storing these assets locally speeds up scene building and avoids download bottlenecks during scene creation.

`pow asset` allow configure the local asset directory location to Nvidia Isaac Sim and also allow switching between different asset folders:

```bash
# Configure the local asset directory
pow asset set /path/to/assets

```
For usage instructions and available options, see the `pow asset` command group in the [CLI Reference](docs/cli-reference.md).

## Validate asset references

`pow lint` checks asset references in `.usda` files. When you change the Isaac Sim version used by a project, it can detect and fix `Assets/Isaac/<major>.<minor>` paths that do not match the `[sim] version` configured in `pow.toml`:

```bash
# Report asset-reference issues
pow lint ./usda

# Rewrite supported asset paths
pow lint fix ./usda
```

See the [Lint Rules Guide](docs/lint-rules.md) for all supported path checks and additional examples.


## Project Structure

After running `pow init`, your project will have the following structure:

```
your-project/
├── .vscode/              # VS Code configuration (launch.json, settings.json, etc.)
├── .modules/             # Third-party modules used in your project, e.g., Pegasus Simulator
├── exts/                 # Your custom Isaac Sim extensions
├── usda/                 # USD scene description files
├── _isaacsim/            # Symlink → ~/.pow/isaacsim/<version> for IntelliSense and autocomplete
├── .gitignore            # Preconfigured gitignore for Isaac Sim projects
├── pow.toml              # Project configuration (sim settings, profiles)
└── pyproject.toml        # Python project manifest
```

`pow init` also creates a **global directory** at `~/.pow` (shared across all projects). The `assets` symlink is added later by `pow asset set`:

```
~/.pow/
├── isaacsim/             # Downloaded Isaac Sim installations
│   ├── 5.1.0/            # Isaac Sim 5.1.0 app files
│   └── 6.1.0/            # Isaac Sim 6.1.0 app files
├── modules/              # Shared modules
├── assets/               # Symlink to the configured local asset directory
└── system.toml           # Global system configuration ([sim] default_version, [asset])
```

To choose which installation `pow sim` and `pow sim check` use when `-v` is
omitted, set the global default in `~/.pow/system.toml`. Leave it empty to use
the newest installed version:

```toml
[sim]
default_version = "6.1.0"
```

## Contribution

See the [Contribution Guide](docs/contributing.md)

Maintainers publishing a new version: see the [Release Guide](docs/releasing.md).

## License

[Apache-2.0](LICENSE).

See [Isaac Sim 6.1 upgrade and validation notes](docs/isaac-sim-6.1.md) for explicit
upgrade/rollback, ROS rebuild requirements, upstream references and manual checks.
