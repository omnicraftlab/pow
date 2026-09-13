# Changelog

All notable changes to the `pow-cli` package will be documented in this file.

## [Unreleased]

- Offer a default-No bundled ROS image rebuild prompt during initialization; report Docker inspection failures separately and preserve existing containers and workspaces.
- Hide setuptools' `setup.py install is deprecated` warning in pow_simros colcon builds (automatic and manual). Existing images need a rebuild (`docker rmi pow_simros_jazzy && pow init`).

Target: v0.4.0 (version bump and publication are separate).

- Add Isaac Sim 6.1.0 installation and selection, retaining 5.1.0.
- Support linux-aarch64 hosts (DGX Spark): `pow init` and `pow sim` install NVIDIA's `linux-aarch64` build of 6.1.0 or 5.1.0, and `pow run` / `pow sim` / `pow sim check` launch it. The bundled ROS Docker image is amd64-only, so `pow init` skips it on aarch64 and `pow ros` / `pow ros build` report it as unavailable.
- Remove Isaac Sim 6.0.1 from the installable versions; projects pinned to it must switch to 6.1.0 or 5.1.0 (existing `~/.pow/isaacsim/6.0.1` installs still launch via `pow sim -v 6.0.1`).
- Default new projects to 6.1.0 unless a global preference is configured; preserve existing project versions and settings.
- Reject unknown 6.1.0 ROS workspace/image/container provenance without changing user state; stop instead of deleting stale container-mounted build directories.
- Remove the mandatory simulator dependency and declare the Python 3.10 TOML fallback.
- Reject failed or unrecognized compatibility-check verdicts; actual 6.1.0 output and GPU workflows still require manual verification.
- Use verified asset namespace mappings; document explicit upgrades, rollback and validation limits.

## [Unreleased]

---

## [0.3.0] - 2026-09-07

### Added

- **`pow lint` rule 4 — Isaac asset version mismatch.** Asset references pointing
  at an `Assets/Isaac/<major>.<minor>` tree other than the one `[sim] version`
  reads from are reported, and rewritten by `pow lint fix` (`version = "6.0.1"`
  → `Assets/Isaac/6.0`). NVIDIA keeps every release's asset tree online, so a
  stage authored against 5.1 kept loading 5.1 assets after the project moved to
  6.0.1 with nothing to show for it. The target version is derived from the
  configured version rather than tabulated, applies to every reference form (S3
  URLs, `pow-assets`/`user-home` aliases, relative paths), and is skipped when
  `pow.toml` sets no version

- **Isaac Sim 6.0.1 support.** `pow init` step 4 now offers the installable
  versions as an arrow-key picker — latest first, marking the latest release and
  any already installed — or takes the version from the new `--sim-version`
  flag, or from `[sim] version` in an existing `pow.toml` you chose to keep. The
  picker falls back to a typed prompt when there is no terminal (piped stdin,
  CI), so the command stays scriptable. Releases live in
  `PowConfig.ISAACSIM_RELEASES`, which pins each version's download URL — 6.0.1
  is served from `downloads.isaacsim.nvidia.com`, not the host used for 5.1.0 —
  and the matching `IsaacSim-<version>` ROS workspace ref cloned during setup.
- `pow sim` / `pow sim check` default `-v` to the Isaac Sim version actually
  installed under `.pow/isaacsim/` instead of a fixed constant.
- **`[sim] default_version` in `~/.pow/system.toml`** — pin the version `pow sim`
  and `pow sim check` use when `-v` is omitted. Resolution order is `-v`, then
  this key, then the newest version installed under `.pow/isaacsim/`; an empty
  value means auto-detect. A pinned version that is not installed prints a
  warning and falls back to the newest installed one. New `system.toml` files
  are created with the key present and empty; existing files are left untouched
  and read as unset.
- `pow sim --help` now lists the options bare `pow sim` accepts (`-v/--version`,
  `--ros`, `--no-ros`), which previously showed up only under
  `pow sim launch --help`.
- **`pow sim check`** — run the Isaac Sim compatibility check from the managed
  installation (`.pow/isaacsim/<version>/isaac-sim.compatibility_check.sh`), with
  `-v/--version` to pick the version. Needs no project and no extra pip
  dependency; the script sets up its own ROS environment (forward
  `-- --no-ros-env` to skip it). `pow sim` is now a command group whose default
  subcommand is `launch` — bare `pow sim [args...]` still launches Isaac Sim and
  forwards raw arguments exactly as before, and `pow sim launch` is the explicit
  form

### Changed

- **`pow init` no longer replaces an existing `pow.toml`.** Choosing to update
  the configuration used to overwrite the file with the bundled template, losing
  custom `exts`, `raw_args`, `ros_bridge`, every `[[profiles]]` block and all
  comments. It now patches only the three settings init asks about — `version`,
  `enable_ros`, `isaacsim_ros_ws` — and leaves the rest of the document, key
  order and comments included, exactly as written. Step 10 lists what changed
  (`version: 5.1.0 → 6.0.1`), and says the file is already up to date when
  nothing moved, in which case it is not rewritten at all. Keys the template has
  and your file lacks are deliberately not back-filled. The step-2 prompt is
  reworded from "override" to "Update settings in existing pow.toml?" to match.
- The `_isaacsim` symlink is re-pointed when `pow init` installs a different
  version, instead of being left on the previous installation. A real directory
  at `_isaacsim` is never deleted; it is reported as an error.
- `pow init` writes the selected `version` into the generated `pow.toml`.
- Isaac Sim's bundled ROS 2 libraries are located by probing
  `exts/isaacsim.ros2.core/<distro>/lib` and then
  `exts/isaacsim.ros2.bridge/<distro>/lib`, so ROS works on 6.0.1, which renamed
  the extension.

### Security

- **ROS containers no longer disable X11 access control with `xhost +`.** When
  `DISPLAY` is set, `pow ros` now copies only the current display's Xauthority
  record into a private temporary file, mounts it read-only in the container,
  and sets the container's `XAUTHORITY` to that file. The host's authority file
  and X server access-control settings are left unchanged, and the temporary
  credentials are removed when the Docker client exits. Headless launches skip
  X11 setup; GUI launches fail with an actionable message when `xauth` or valid
  display credentials are unavailable. Existing running containers must be
  recreated to receive the new authentication mount.
- An Isaac Sim version can no longer escape `.pow/isaacsim/`: versions used as a
  path component are validated, and download URLs are only ever read from the
  release registry, never built from a supplied version string.
- Archive members are chmod-ed via the path `zipfile` actually wrote rather than
  a recomputed one, so a crafted zip cannot change permissions outside the
  install directory; setuid/setgid bits in the archive are dropped.

### Fixed

- A `pow.toml` that is not valid TOML is reported as
  `pow.toml is not valid TOML: <parse error>` with a pointer to fix or delete it,
  instead of a raw `tomllib` traceback. No command rewrites the file to make it
  parse.
- An interrupted Isaac Sim download no longer leaves a truncated zip that the
  next `pow init` mistakes for a complete archive: downloads land on a `.part`
  file and are renamed only once finished.
- Execute permissions are restored before `post_install.sh` runs, so an archive
  without Unix mode bits no longer fails the install.
- `pow asset` resolves the `.kit` file from the project's configured Isaac Sim
  version instead of a hardcoded `5.1.0` path.
- **`pow sim check` could report nothing at all** — inside Isaac Sim's bundled
  Python the check extension failed with `ModuleNotFoundError: No module named
  'packaging'` (then `'setuptools'`) and never produced a verdict. The vendor
  launcher `isaac-sim.compatibility_check.sh` never sources
  `setup_python_env.sh`, so whether `packaging` was importable depended on kit's
  extension load order. pow now puts the installation's own bundled module
  directories on `PYTHONPATH` and no longer forwards the host `PYTHONPATH` (which
  typically targets another Python version, the same reason the ROS bridge
  environment strips it)
- **`pow sim check` exited 0 when the check produced no result** — Isaac Sim exits
  0 even when the check app fails to start. The command now streams the output and
  fails with a clear message if no `System checking result:` line appears; a
  non-zero exit code from the check still takes priority

### Removed

- **`pow check`** — the standalone Isaac Sim compatibility check command has been
  removed, replaced by `pow sim check` above. It ran the check through the pip
  `isaacsim` entry point, so pow-cli no longer depends on the
  `isaacsim[compatibility-check]` extra and `isaacsim-app` is no longer installed
  as a transitive dependency
- The `packaging` and `setuptools` runtime dependencies, which existed only for
  that pip-based check. `pow sim check` reads those modules from the Isaac Sim
  installation instead

---

## [0.2.0] - 2026-07-28

Stable release of the 0.2.0 line, promoted from `0.2.0-rc.2` with no functional
changes.

Everything new since `0.1.1` is listed in the two release candidate entries
below — headline items: the new `pow sim` and `pow ros build` commands, the
`ros_bridge` and `ros_docker_image` config keys, Jazzy-only ROS 2 support
(Humble removed), a faster `pow init` that no longer builds the ROS workspace,
and fixes for `rosdep install`, `cpu_performance_mode`, and `ros2` tab
completion inside the container.

---

## [0.2.0-rc.2] - 2026-07-28

### Added

- **`pow sim`** — run Isaac Sim from any directory, with no project required: no `pyproject.toml` check and `pow.toml` is never read. Launches the default version (`5.1.0`, override with `-v/--version`) and forwards raw arguments straight to `isaac-sim.sh` (`pow sim -- --no-window`). The ROS 2 bridge environment is loaded by default (`--ros jazzy`); pass `--no-ros` to launch with the inherited environment instead
- **`pow ros build`** — build the custom image from `ros_dockerfile` without re-running `pow init`; builds the `pow_simros_jazzy` base image first if it is missing, and supports `--no-cache`. `pow ros` is now a command group (bare `pow ros [args...]` usage is unchanged; `pow ros launch` is the explicit form)
- **`ros_bridge` config in `pow.toml`** — choose which Isaac Sim internal ROS 2 bridge libs to load (`jazzy` or `humble`, default `jazzy`), i.e. which `exts/isaacsim.ros2.bridge/<distro>/lib` is added to `LD_LIBRARY_PATH` when `enable_ros = true`. Overridable per profile. Previously the bridge was inferred from the host Ubuntu version with no way to override it; an unsupported value is now rejected with a clear error
- **Tab completion for the `pow init` ROS workspace path** — step 6's "Path to clone IsaacSim-ros_workspaces" prompt now completes filesystem paths on <kbd>Tab</kbd> like a shell: unique directories complete inline (no stray trailing space, so the next segment can be typed straight away), ambiguous prefixes list candidates, and `~` is kept in the stored path. Trailing separators and whitespace are trimmed before the value is written to `pow.toml`

### Changed

- **Breaking (vs 0.2.0-rc.1):** the `ros_container_name` config key was renamed to `ros_docker_image`. The container name is no longer configured directly — it is derived from the image name (`/` and `:` replaced with `_`), so default setups now get a container named `pow_simros_jazzy` instead of `pow_simros`
- **Breaking (vs 0.2.0-rc.1):** ROS 2 Humble support was removed — the ROS workspace and docker integration now support Jazzy only (`Dockerfile.simros_humble` deleted). Isaac Sim itself still runs on Ubuntu 22.04 and 24.04; Jazzy workspaces build on both
- **`pow init` no longer builds the Isaac Sim ROS workspace.** Step 6 only clones `IsaacSim-ros_workspaces`; the ROS 2 bridge comes from Isaac Sim's own prebuilt libs (selected by `ros_bridge`), so init is much faster and no longer runs a Docker build for the workspace. It reports the bridge distro in use instead of a build result
- `pow init` no longer creates the `scripts/`, `.assets/`, and `standalone/` project folders (only `exts/`, `.modules/`, `usda/`). A manually created `scripts/` folder is still mounted into the ROS container when present
- The `pow_simros_jazzy` image now resolves workspace dependencies with `rosdep install` at build time instead of building the workspace, and source-only packages (`topic_based_ros2_control`) are staged in `/opt/pow/extra_src` and copied into `/jazzy_ws/src` at container start, so the runtime volume mount no longer shadows them

### Fixed

- **`rosdep install` failed inside the Jazzy container** — three causes, all fixed (requires rebuilding the image): the Ubuntu 24.04 base image's stock `ubuntu` user took UID 1000 and collided with the mapped host user, so `HOME` pointed at `/home/ubuntu` while the host `~/.ros` was mounted at `/home/hostuser/.ros`; the per-user rosdep cache was empty because `rosdep update` had run as root at build time, giving "your rosdep installation has not been initialized"; and `ros-jazzy-ros-testing` was missing from the image
- **`cpu_performance_mode` asked for the sudo password on every launch** — `pow run` / `pow python` now read the current CPU governor from `/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor` first and run no `sudo` at all when it is already `performance`, so the password is normally needed once instead of every launch. When sudo credentials are still cached the governor is set without the "requires sudo" notice, and hosts without `cpupower` or without cpufreq support now report and skip rather than prompting for a password to no purpose. The interactive prompt itself is unchanged when the governor really has to be switched
- **`ros2` tab completion inside the `pow_simros` container** — the entrypoint sourced ROS before exec'ing bash, which carried environment variables but not bash completion functions. Interactive shells now re-source `/opt/ros/jazzy/setup.bash` and the workspace overlay via `/etc/bash.bashrc`, so `ros2` / `colcon` autocomplete works without manually sourcing `setup.bash` (requires rebuilding the image)

---

## [0.2.0-rc.1] - 2026-06-14

### Added

- **Custom ROS Dockerfile (`pow init`)**
  - New `ros_dockerfile` config in `pow.toml` — point to a project-local Dockerfile that layers on top of the bundled `pow_simros_<distro>` base image
  - New `ros_container_name` config in `pow.toml` — set a custom container/image name (defaults to `pow_simros`)
  - `pow init` now builds the custom image automatically after the base image when `ros_dockerfile` is set
  - `pow ros` launches the custom image when configured, otherwise falls back to the base image
- **Version flag (`pow --version` / `pow -v`)** — quickly check the installed `pow-cli` version from the command line

### Changed

- Updated CLI description to *"Manage Isaac Sim projects and simplify the development workflow"*
- Renamed status messages from *"Isaac ROS workspace"* to *"Isaac Sim ROS workspace"* for clarity
- Container name is now read from `ros_container_name` config instead of being hard-coded

---

## [0.1.1] - 2026-06-14

### Fixed

- **ROS Docker container: `colcon build` fails for new packages** — The container
  entrypoint now detects stale build artifacts (left from a host-path build) and
  cleans `build/`, `install/`, and `log/` automatically before rebuilding.

---

## [0.1.0] - 2026-06-05

First stable release of `pow-cli`, promoted from `0.1.0-rc.1` with documentation improvements.


### Fixed

- Installation guide referenced incorrect `pow-cli` version

### Changed

- Improved README wording, tagline, and Profiles section

---

## [0.1.0-rc.1] - 2026-05-11

### Added

- **Asset Management (`pow asset`)**
  - `pow asset list` — list available Isaac Sim & Omniverse assets
  - `pow asset add` — download and register assets into the local asset folder (only support `isaacsim_5_1_0` for now)
  - `pow asset set / unset` — set/unset target local asset folder
  - `pow asset info` — display current local asset folder information
- **Linter (`pow lint`)**
  - New `pow lint` and `pow lint --fix` commands for `.usda` files
  - Detects absolute/relative local asset paths and rewrites them with correct aliases or asset urls (`user-home`, `pow-assets`)
  - Rule for validating `simros_ws` relative paths
- **ROS Integration (`pow ros`)**
  - `pow ros` command to build, launch, and attach to ROS 2 Docker containers
  - Verbose mode (`--verbose`) for runtime diagnostics
  - Separate Dockerfiles for ROS Humble and Jazzy distributions
  - Project `scripts/` directory mounted into the container
  - PyTorch with CUDA support available inside the container
  - `isaacsim_ros_ws` working directory configurable in `pow.toml`
- **Runner Improvements**
  - (experimental) `pow run --open <file>` option to open a USD stage on launch 
  - Non-existent `ext_folders` entries are now silently skipped instead of auto-created
- **Other**
  - `pow python` command with `--profile` flag for running standalone app under specified version of Isaac Sim's Python
  - `user-home` aliases automatically configured during `pow init`
  - `usda/` folder added to default project structure
  - `extends` support in `pow.toml` for profile-based configuration

### Fixed

- ROS Jazzy container build failure on Ubuntu 24.04
- CUDA version pinned to 12.1 for deterministic ROS builds
- `.ros` / `.ros2` mount and permission issues in the SimROS container
- SimROS entrypoint no longer warns when host-user directory already exists
- `pow run` no longer calls `open_stage` when no path is provided
- `pow asset unset` no longer accidentally removes `user-home` alias
- Duplicate and deprecated keys in generated `.vscode/settings.json`
- `pow init` now respects existing `isaacsim_ros_ws` value in existing `pow.toml`
- `pow ros` correctly attaches to an already-running container

### Changed

- Rewrite and refactor all core functionality of pow-cli
- Move commands under group `pow sim` to root `pow` command instead
- Remove pow-foxglove from repository 
- ROS-related logic extracted into dedicated `ros_manager.py` module
- CLI and core layers refactored for clearer separation of concerns

## [0.1.0a3] - 2026-01-27

### Fixed

- Fixed incorrect Ubuntu base Docker image version in `pow sim init` ROS workspace setup. Now correctly uses Ubuntu 22.04 for ROS Humble and Ubuntu 24.04 for ROS Jazzy (previously hardcoded to 22.04 for both).

## [0.1.0a2] - 2025-12-25

### Fixed

- `pow sim init` now allows overwriting existing VS Code settings to resolve Pylance `reportMissingImports` errors for Isaac Sim packages.
- Fixed an issue where the `ros_enable` flag did not correctly disable ROS workspace sourcing when set to `false` in an existing `pow.toml`.

## [0.1.0a1] - 2025-12-23

### Added

- Initial alpha release of Isaac Powerpack CLI (`pow`)
- **Core CLI Structure**
  - Main entry point with Click-based command group architecture
  - Hierarchical command organization under `pow sim` namespace

- **Simulation Commands (`pow sim`)**
  - `pow sim run` - Run Isaac Sim applications with automatic environment setup
    - Auto-discovery of project root via `pow.toml` configuration
    - ROS 2 workspace sourcing support
    - Isaac Sim setup file sourcing
    - Configurable app path and extension loading
  - `pow sim init` - Initialize Isaac Sim development environment
    - VS Code settings generation for Isaac Sim development
    - Asset browser cache fix utility
    - Project configuration scaffolding
  - `pow sim check` - Run Isaac Sim compatibility checker
    - Validates system compatibility with Isaac Sim requirements
  - `pow sim info` - Display Isaac Sim configuration information
    - Show local assets path configuration (`-l, --local-assets` flag)

- **Resource Management (`pow sim add`)**
  - `pow sim add local-assets` - Configure local Isaac Sim assets
    - Updates `isaacsim.exp.base.kit` with local asset paths
    - Configures asset browser and content browser folders
    - Supports versioned asset directories

### Dependencies

- `click>=8.1.7` - Command line interface framework
- `toml>=0.10.2` - TOML configuration file parsing
- Python 3.10+ required
