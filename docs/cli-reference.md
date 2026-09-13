# CLI Reference

## `pow init`

Initialize an Isaac Sim project. All projects are isolated from each other. Only file and isaacsim app in global `~/.pow` are shared between projects.

<img src="./public/pow_architecture_outline.jpeg" alt="pow_architecture" width="600" />

This interactive command walks through a 10-step setup:

1. Validates the project directory (requires `pyproject.toml`)
2. Checks for existing `pow.toml` configuration, offering to update it in place
3. Creates the `.pow` global folder, any missing subfolders, and `system.toml`
4. Selects the Isaac Sim version, then downloads and installs it in `.pow/isaacsim/<version>`
5. Applies post-install optimizations
6. Sets up ROS integration (optional — builds Docker images). The workspace path prompt supports shell-style <kbd>Tab</kbd> completion: unique directories complete inline, ambiguous prefixes list candidates, and `~` is preserved
7. Creates project structure (`exts/`, `.modules/`, `usda/`)
8. Symlinks the managed Isaac Sim installation into the project for intellisense/code completion
9. Configures VS Code settings
10. Generates `pow.toml` configuration

```bash
# Pick the version interactively
pow init

# Or select it up front, skipping the picker
pow init --sim-version 5.1.0
```

| Option          | Description                                                     |
| :-------------- | :-------------------------------------------------------------- |
| `--sim-version` | Isaac Sim version to install: `6.1.0` or `5.1.0`. Skips the picker |

The version is resolved in this order:

1. `--sim-version`
2. `[sim] version` from an existing `pow.toml` you chose to keep at step 2
3. The step-4 picker, with the cursor on the global default, or `6.1.0` when unset

Step 4 lists the installable versions latest first, marking which one is the
latest release and which are already present in `~/.pow/isaacsim/`. Move with
<kbd>↑</kbd>/<kbd>↓</kbd> and confirm with <kbd>Enter</kbd>:

```
[4/10] 📦 Isaac Sim App: Select a version to install

   ❯ 6.1.0 (latest)
     5.1.0 (installed)

   ↑/↓ to move, Enter to confirm
```

> [!NOTE]
> The picker needs a terminal. When stdin is piped, or in CI, `pow init` falls
> back to a typed prompt (`Select Isaac Sim version [6.1.0/5.1.0] (6.1.0):`), so
> the command stays scriptable. Use `--sim-version` to skip the question entirely.

The chosen version drives the download, the matching `IsaacSim-<version>` ROS
workspace tag cloned at step 6, the `_isaacsim` symlink at step 8, and the
`version` key written to `pow.toml` at step 10. Re-running `pow init` with a
different version re-points `_isaacsim` at the new installation.

On an aarch64 host (DGX Spark), step 4 lists only the versions NVIDIA publishes a
`linux-aarch64` build for and downloads that build. Step 6 still clones the ROS
workspace and uses Isaac Sim's bundled ROS 2 bridge, but skips building the
`pow_simros` image: its base, `osrf/ros:jazzy-desktop`, is published for amd64 only.

### Re-running `pow init` on an existing project

Step 2 asks whether to update the settings in an existing `pow.toml`. Either
answer keeps the file:

- **No** — the file is not touched at all, and its `version`, `enable_ros` and
  `isaacsim_ros_ws` are reused for the rest of the run.
- **Yes** — `pow init` re-asks for those three settings and writes **only** those
  three keys back. Everything else in the file survives: custom `exts`,
  `raw_args`, `ros_bridge`, every `[[profiles]]` block, key order and comments.
  Step 10 lists what changed, e.g. `version: 5.1.0 → 6.1.0`.

Keys the current template has but your file lacks are not added — pow defaults
every missing setting, so an older `pow.toml` keeps working as it is.

A `pow.toml` that is not valid TOML is never rewritten. `pow init` (like every
other command) stops with `pow.toml is not valid TOML: ...` and leaves the file
for you to fix.

---

## `pow run`

Run Isaac Sim with the configured profile and extensions from `pow.toml`. See more detail for `pow.toml` configuration in [Configuration Guide](docs/configuration.md).

```bash
# Run with default profile
pow run

# Run with a named profile
pow run -p perf

# Open a specific USD file
pow run -o /path/to/scene.usd

# Pass extra arguments directly to Isaac Sim
pow run -- --/renderer/enabled=gpu
```

| Option              | Description                                        |
| :------------------ | :------------------------------------------------- |
| `-p`, `--profile`   | Profile name from `pow.toml` (default: `default`)  |
| `-o`, `--open`      | Path to a USD file to open on launch               |

> [!WARNING]
> `-o` or `--open` is still in experiment. We have found bug that cause **missing assets** issue when opening scenes using this flag. Suggestion to avoid this problem is by opening the scene via GUI or load scene with `isaacsim api` in your custom extension.

---

## `pow sim`

Run Isaac Sim from **any** directory. Unlike `pow run`, this command needs no project: it does not require a `pyproject.toml` and never reads `pow.toml`, so there is no profile, no `ext_folders`, and no `exts`. It simply launches `.pow/isaacsim/<version>/isaac-sim.sh` and forwards every unrecognized argument straight to it.

Use it to open Isaac Sim outside a project — inspecting a stray USD file, or sanity-checking the installation.

The version is resolved in this order:

1. the `-v`/`--version` option;
2. `[sim] default_version` in `~/.pow/system.toml`, when set;
3. the newest release installed under `.pow/isaacsim/` (the sole installation when there is one);
4. the latest release supported by the installed pow CLI when nothing is installed.

Pin a default when several versions are installed by editing `~/.pow/system.toml`:

```toml
[sim]
default_version = "5.1.0"
```

If the pinned version is missing, `pow sim` installs it automatically before running. Downloads are limited to releases supported by the installed pow CLI; other versions can still run when already installed. See [Configuration](configuration.md#global-settings-powsystemtoml).

`pow sim` is a command group whose default subcommand is `launch`: bare `pow sim [args...]` and `pow sim launch [args...]` are equivalent.

Before launch or compatibility checking, pow completes the global setup from init steps 1, 3, 4, and 5: it resolves the global directory, creates missing global folders and `system.toml`, installs the selected Isaac Sim version if needed, and creates the missing asset-browser cache. This runs automatically without prompts. A ready installation produces no additional setup output, and a setup failure stops the command with a nonzero exit code.

These commands work without `pyproject.toml` and ignore `pow.toml`. An optional `[tool.pow-cli] global_dir_name` in a `pyproject.toml` above the current directory still selects the global directory. Existing global settings and cache files are preserved. No project structure, ROS workspace, or editor configuration is created.

An installation must contain `isaac-sim.sh`; `pow sim check` also requires `isaac-sim.compatibility_check.sh`. Incomplete installations are repaired, with their original contents kept under `<global>/isaacsim-backups/` and the backup location printed. A failed repair restores the original installation.

```bash
# Launch the installed version with the jazzy ROS 2 bridge
pow sim

# Launch without the ROS 2 bridge environment
pow sim --no-ros

# Use the humble bridge instead
pow sim --ros humble

# Launch a different installed version
pow sim -v 5.0.0

# Pass raw arguments directly to Isaac Sim
pow sim -- --no-window --/renderer/enabled=gpu

# Same as bare `pow sim`, written explicitly
pow sim launch -- --no-window
```

| Option              | Description                                                  |
| :------------------ | :----------------------------------------------------------- |
| `-v`, `--version`   | Isaac Sim version to run (default: `system.toml`, else newest installed, else latest supported) |
| `--ros`             | ROS 2 bridge distro: `jazzy` (default) or `humble`           |
| `--no-ros`          | Launch without the ROS 2 bridge environment; wins over `--ros` |

> [!NOTE]
> Because the ROS 2 bridge is enabled by default, `pow sim` clears the host ROS environment and points `LD_LIBRARY_PATH` at Isaac Sim's bundled bridge libs — the same environment `pow run` builds when `enable_ros = true`. Pass `--no-ros` to inherit your shell environment untouched.
>
> `-v` on this subcommand selects the Isaac Sim version; `pow -v` (on the root command) still prints the pow CLI version.

### `pow sim check`

Run the Isaac Sim compatibility check to verify your system meets the requirements. It runs `.pow/isaacsim/<version>/isaac-sim.compatibility_check.sh` from the managed installation and needs no project. Version selection and automatic prerequisite setup follow `pow sim` above.

```bash
# Check the installed version
pow sim check

# Check a different installed version
pow sim check -v 5.0.0

# Skip the check script's own ROS environment setup
pow sim check -- --no-ros-env
```

| Option              | Description                                        |
| :------------------ | :------------------------------------------------- |
| `-v`, `--version`   | Isaac Sim version to check (default: `system.toml`, else newest installed, else latest supported) |

> [!NOTE]
> `--ros` / `--no-ros` do not apply here: the check script sources its own ROS environment. Forward `-- --no-ros-env` to skip that step. Raw arguments after `--` go straight to the script.
>
> Your shell's `PYTHONPATH` is **not** forwarded (it usually points at a ROS install built for a different Python version). Instead, pow puts the installation's own bundled module directories on `PYTHONPATH`, because the vendor launcher never sources `setup_python_env.sh` and the check extension needs `packaging` — without it the extension fails to import and reports nothing.
>
> A run that prints no `System checking result:` line is reported as a failure (exit 1), since Isaac Sim exits 0 even when the check app fails to start.

---

## `pow python`

Run Isaac Sim's bundled Python interpreter (`.pow/isaacsim/<version>/python.sh`)for running standalone isaac sim application.

```bash
# Run a standalone script
pow python my_script.py

# Run inline Python
pow python -c "import omni; print(omni.__version__)"

# Use a specific profile
pow python -p perf my_script.py
```

| Option              | Description                                        |
| :------------------ | :------------------------------------------------- |
| `-p`, `--profile`   | Profile name from `pow.toml` (default: `default`)  |

---

## `pow ros`

Launch the ROS Docker container for ROS development. Requires ROS integration to be enabled during `pow init`. By default this runs the bundled `pow_simros_jazzy` image (ROS 2 Jazzy is the only supported distribution); when `ros_dockerfile` / `ros_docker_image` are set in `pow.toml`, it runs your custom image instead. The container is named after the image (characters like `/` and `:` replaced with `_`). See more about the ROS 2 enable flag and custom images in the [Configuration Guide](docs/configuration.md). ROS Docker images are not available on aarch64 hosts, so `pow ros` and `pow ros build` stop with an error there.

```bash
# Start an interactive ROS bash session
pow ros

# Show detailed container launch feedback
pow ros -v

# Pass a custom command to the container
pow ros -- ros2 topic list

# Same as bare `pow ros`; use when a forwarded arg collides with a subcommand name
pow ros launch <args>
```

| Option              | Description                              |
| :------------------ | :--------------------------------------- |
| `-v`, `--verbose`   | Show detailed feedback during launch     |

GUI launches require host `xauth` and credentials for the current `DISPLAY`.
pow reads `XAUTHORITY` (or the default `~/.Xauthority`), copies only that
display's credentials into a private temporary file, and mounts the copy
read-only into the container. It does not change X11 access control. The copy
is removed when the Docker client returns; a detached container retains its
existing bind mount until it exits. Attachments reuse the container's mount.

If authentication fails, install `xauth` (`sudo apt install xauth`) and launch
from a desktop terminal with valid `DISPLAY` and `XAUTHORITY`. For a headless
session, use `env -u DISPLAY pow ros`. Recreate containers started with older
pow versions to receive the authentication mount. GUI applications in the
container still have access to your X11 desktop through this cookie.

### `pow ros build`

Build the custom ROS image from the Dockerfile referenced by `ros_dockerfile` in `pow.toml`, tagging it with `ros_docker_image`. If the base `pow_simros_jazzy` image is missing, it is built first (this requires the ROS workspace set up by `pow init`).

```bash
pow ros build

# Bypass the Docker layer cache
pow ros build --no-cache
```

| Option              | Description                                    |
| :------------------ | :--------------------------------------------- |
| `--no-cache`        | Build without using the Docker layer cache     |

---

## `pow asset`

Group of commands to manage Isaac Sim local assets.

### `pow asset set <PATH>`

Set the local asset path. Creates a symlink, registers aliases in `omniverse.toml`, and patches Isaac Sim configs.

```bash
# Set asset path with all alias support (default)
pow asset set /path/to/assets

# Set with specific alias support
pow asset set /path/to/assets -a isaacsim
pow asset set /path/to/assets -a simready

# Set without any alias patching
pow asset set /path/to/assets -a none
```

| Option                    | Description                                                |
| :------------------------ | :--------------------------------------------------------- |
| `-a`, `--alias-support`   | Alias target: `isaacsim`, `simready`, or `none` (repeatable) |


> [!NOTE]
> Currently, we only support `isaacsim` assets and `none` alias. We will add `simready` assets download support and others in the future.

### `pow asset unset`

Remove the local asset configuration — clears symlink, config, and alias patches.

```bash
pow asset unset
```

### `pow asset info`

Show the current local asset configuration status.

```bash
pow asset info
```

### `pow asset list`

List all supported assets in the registry.

```bash
pow asset list
```

### `pow asset add <TARGET>`

Install assets by group or name.

```bash
# Install by group (default)
pow asset add local-assets

# Install by name
pow asset add -n nova_carter_sensors

# Keep downloaded files or use assets to install from this path
pow asset add local-assets -k /path/to/keep
```

| Option          | Description                                      |
| :-------------- | :----------------------------------------------- |
| `-n`, `--name`  | Install asset by name                            |
| `-g`, `--group` | Install asset by group (default behavior)          |
| `-k`, `--keep`  | Keep downloaded files or use assets to install from this path |

---

## `pow lint`

Check `.usda` files for asset path compatibility issues. Defaults to `dry-run` when no subcommand is given.

Rule 4 keeps `Assets/Isaac/<version>` references in step with `[sim] version` in
`pow.toml`, so a project moved to a new Isaac Sim release stops silently loading the
previous release's assets.

### `pow lint [dry-run] [PATH]`

Report lint issues without modifying files.

```bash
# Lint current directory
pow lint

# Lint a specific path
pow lint ./usda

# Short output (file + line only)
pow lint -s
```

### `pow lint fix [PATH]`

Automatically fix lint issues in `.usda` files.

```bash
pow lint fix
pow lint fix ./usda
pow lint fix -s
```

| Option          | Description                          |
| :-------------- | :----------------------------------- |
| `-s`, `--short` | Show feedback with file path and line number only |

For a detailed explanation of each rule, patterns, and examples, see the [Lint Rules Guide](lint-rules.md).

---

## `pow --version`

Print the installed Pow CLI version.

```bash
pow --version
# or
pow -v
```

### Rebuilding an incompatible ROS image during initialization

When an existing bundled ROS image is unlabelled or targets another simulator,
`pow init` asks whether to rebuild it for the selected version. The default is No;
declining stops initialization. Accepting builds with the selected workspace and
version label, retaining Docker's build cache and updating the existing image tag.
Custom-image building continues only after the bundled build succeeds.

The rebuild does not delete images, containers, volumes, or workspace files.
Existing containers keep their old image: preserve any needed data and explicitly
recreate them to use the new image. Docker inspection errors are reported directly
and do not trigger the rebuild prompt. A failed build stops initialization and
reports its diagnostic output.

### Picking up bundled ROS image changes

`pow init` and `pow ros` reuse an existing `pow_simros_<distro>` image as long as its
simulator label matches, so changes to the bundled Dockerfile (for example, the filter
that hides setuptools' `setup.py install is deprecated` warning in colcon builds) take
effect only after the image is rebuilt. With the ROS container stopped, remove the
image and let `pow init` build it again:

```bash
docker rmi pow_simros_jazzy && pow init
```

If `ros_dockerfile` is set in pow.toml, run `pow ros build` afterwards so the custom
image is layered on the new base.
