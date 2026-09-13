# Configuration

After running `pow init`, a `pow.toml` file is generated in your project root. This file controls how Isaac Sim is launched, which extensions are loaded, and how profiles customize runtime behavior.

## Default Configuration

The `[sim]` section defines the base (default) settings used by `pow run`:

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
```

### Settings Reference

| Key                    | Type       | Default                              | Description |
|:-----------------------|:-----------|:-------------------------------------|:------------|
| `version`              | `string`   | `"6.1.0"`                            | Isaac Sim version to use. One of `6.1.0` or `5.1.0`. `pow init` installs this version when you keep an existing `pow.toml`. |
| `ext_folders`          | `string[]` | `["./exts"]`                         | Directories to search for custom extensions. |
| `cpu_performance_mode` | `bool`     | `false`                              | Enable CPU performance governor via `cpupower` (requires `sudo`). Skipped when the governor is already `performance`, so the password is normally asked once rather than on every launch — see the note below. |
| `headless`             | `bool`     | `false`                              | Run Isaac Sim without the GUI window. |
| `enable_ros`           | `bool`     | `false`                              | Source the ROS 2 workspace environment before launching. |
| `ros_bridge`    | `string`   | `"jazzy"`                            | ROS distro of the Isaac Sim internal ROS2 bridge libs to load (`jazzy` or `humble`). Selects which `exts/isaacsim.ros2.core/<distro>/lib` (`isaacsim.ros2.bridge` before Isaac Sim 6.0) is added to `LD_LIBRARY_PATH` when `enable_ros = true`. Overridable per profile. |
| `isaacsim_ros_ws`      | `string`   | `"~/IsaacSim-ros_workspaces"`        | Path to the cloned IsaacSim-ros_workspaces directory. |
| `ros_dockerfile`       | `string`   | `""`                                 | Path (relative to project root) to a custom ROS Dockerfile built on top of the bundled `pow_simros_jazzy` base image. Empty = use the base image only. |
| `ros_docker_image`     | `string`   | `"pow_simros"`                       | Docker image name for the ROS image launched by `pow ros` (the custom image tag when `ros_dockerfile` is set). The container name is derived from the image name (`/` and `:` replaced with `_`). |
| `exts`                 | `string[]` | `["isaacsim.code_editor.vscode"]`    | Extensions to enable on launch. |
| `raw_args`             | `string[]` | `["--/renderer/raytracingMotion/enabled=false"]` | Extra CLI arguments passed directly to Isaac Sim. |

> [!NOTE]
> **When `cpu_performance_mode` asks for your password.** Before touching `cpupower`, pow reads `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor`. If every CPU is already on the `performance` governor it runs no `sudo` at all, so later launches never prompt. It also skips (instead of prompting pointlessly) when `cpupower` is not installed or the host has no cpufreq support.
>
> The governor persists until something changes it, so you are normally asked once per boot. On GNOME desktops, `power-profiles-daemon` owns the governor and re-applies it whenever the power profile changes (for example a laptop switching between AC and battery) — after that pow will ask again. To remove the prompt entirely, add a narrowly scoped drop-in:
>
> ```bash
> echo "$USER ALL=(root) NOPASSWD: $(command -v cpupower)" | sudo tee /etc/sudoers.d/pow-cpupower
> sudo chmod 0440 /etc/sudoers.d/pow-cpupower
> ```

---

## Global Settings (`~/.pow/system.toml`)

`pow init`, `pow sim`, and `pow sim check` create `~/.pow/system.toml` when missing. It holds settings shared by every project on the machine:

```toml
[asset]
use_local_asset = false
local_asset_path = ""

[sim]
default_version = ""
```

| Section   | Key                | Type     | Default | Description |
|:----------|:-------------------|:---------|:--------|:------------|
| `[sim]`   | `default_version`  | `string` | `""`    | Isaac Sim version used by `pow sim` and `pow sim check` when `-v` is omitted. Empty means auto-detect the newest version installed under `.pow/isaacsim/`. |
| `[asset]` | `use_local_asset`  | `bool`   | `false` | Managed by `pow asset attach` / `pow asset detach` — do not edit by hand. |
| `[asset]` | `local_asset_path` | `string` | `""`    | Managed by `pow asset attach` / `pow asset detach` — do not edit by hand. |

`default_version` is the one key meant to be edited directly. Set it when several Isaac Sim versions are installed and you normally work with one that is not the newest:

```toml
[sim]
default_version = "5.1.0"
```

`-v` on the command line still wins over it. If the pinned version is missing, `pow sim` and `pow sim check` automatically install it before running. A missing version must be supported by the installed pow CLI to be downloaded; already-installed versions remain usable. With no pin or installed version, pow installs its latest supported release. This is separate from `[sim] version` in a project's `pow.toml`, which is what `pow run` uses — `pow sim` never reads `pow.toml`.

## Custom ROS Image

By default, `pow init` builds a bundled ROS 2 Jazzy image tagged
`pow_simros_jazzy`, and `pow ros` runs it in a container named after the image
(`pow_simros_jazzy`). Jazzy is the only supported ROS distribution.

To add your own ROS packages or tooling, point `ros_dockerfile` at a Dockerfile
in your project that extends the bundled base image:

```toml
[sim]
enable_ros = true
ros_dockerfile = "docker/Dockerfile.simros"
ros_docker_image = "my_robot_sim"
```

Your custom Dockerfile **must** start with `FROM pow_simros_jazzy` so it
inherits the base image's workspace and entrypoint:

```dockerfile
FROM pow_simros_jazzy

RUN apt-get update && apt-get install -y ros-jazzy-my-pkg
# ... your customizations
```

When `ros_dockerfile` is set, `pow init` first builds the base image, then builds
your Dockerfile and tags it with `ros_docker_image`. `pow ros` then runs that
custom image in a container named after the image (with characters like `/` and
`:` replaced by `_`).

> [!NOTE]
> `pow.toml` is written at the end of `pow init`. After setting `ros_dockerfile`
> and creating your Dockerfile, run `pow ros build` to (re)build the custom
> image without re-running the full init.

---

## Profiles

Profiles let you define named sets of overrides that you can switch between at runtime:

```bash
pow run                  # Uses the default [sim] settings
pow run -p perf          # Uses the "perf" profile
pow run -p my_profile    # Uses a custom profile you defined
```

### Defining a Profile

Add a `[[profiles]]` entry in `pow.toml`. Each profile requires a `name` and can optionally `extends` another profile:

```toml
[[profiles]]
name = "perf"
extends = "default"
cpu_performance_mode = true
headless = false
```

- **`name`** — The identifier you pass to `pow run -p <name>`.
- **`extends`** — Which profile to inherit settings from. Use `"default"` (or omit) to inherit from `[sim]`. You can also point to another profile name for multi-level inheritance.

### Override vs Append

There are two ways a profile can modify list values from its base:

#### Override (replace the entire list)

Assigning a key directly **replaces** the base value completely:

```toml
[[profiles]]
name = "minimal"
extends = "default"
# This REPLACES the default exts list entirely
exts = ["your.custom.extension"]
```

#### Append (extend the base list)

Using the `.add` suffix **appends** items to the inherited list:

```toml
[[profiles]]
name = "perf"
extends = "default"
# This APPENDS to the default raw_args list
raw_args.add = [
    "--/rtx-transient/dlssg/enabled=true",
    "--/rtx/reflections/enabled=false",
]
```

The `.add` keyword works with any list-type setting (`exts`, `raw_args`, `ext_folders`, etc.).

> [!NOTE]
> The `.add` suffix only works with list values. Using it on a non-list setting (e.g., `headless.add`) will produce an error.

### Profile Inheritance Chain

Profiles can extend other profiles, not just `"default"`:

```toml
[sim]
exts = ["isaacsim.code_editor.vscode"]
raw_args = ["--/renderer/raytracingMotion/enabled=false"]

[[profiles]]
name = "perf"
extends = "default"
cpu_performance_mode = true

[[profiles]]
name = "perf-headless"
extends = "perf"
headless = true
```

In this example:
- `pow run -p perf` → inherits `[sim]` + enables `cpu_performance_mode`
- `pow run -p perf-headless` → inherits `perf` (which inherits `[sim]`) + enables `headless`

> [!WARNING]
> Circular inheritance (e.g., profile A extends B, B extends A) is detected and will produce an error.

---

## Full Example

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
# Override exts entirely
exts = ["your.custom.extension"]
# Append additional raw_args
raw_args.add = [
    # Enable framegen 2x (support only for RTX 50 series)
    "--/rtx-transient/dlssg/enabled=true",
    "--/rtx-transient/internal/dlssg/interpolatedFrameCount=1",
    # Disable rtx features for performance
    "--/rtx/reflections/enabled=false",
    "--/rtx/translucency/enabled=false",
]

[[profiles]]
name = "headless"
extends = "default"
headless = true
```
