# Lint Rules

`pow lint` scans `.usda` files for asset reference paths (written as `@path/to/asset.usd@`) that use relative or absolute filesystem paths. These break when the project is moved to another machine or shared with a team. The linter rewrites them to use pow's **Omniverse aliases** for portability.

There are currently 4 rules that detect specific patterns of paths and replace with the aliases:

| # | Rule Name | Detects |
|:--|:-----|:--------|
| 1 | [Relative `.pow/assets` paths](#rule-1--relative-powassets-paths) | `@../../.pow/assets/...@` |
| 2 | [Absolute home directory paths](#rule-2--absolute-home-directory-paths) | `@/home/username/...@` |
| 3 | [Relative ROS workspace paths](#rule-3--relative-ros-workspace-paths) | `@../../../../IsaacSim-ros_workspaces/...@` |
| 4 | [Isaac asset version mismatch](#rule-4--isaac-asset-version-mismatch) | `@.../Assets/Isaac/5.1/...@` when `version = "6.1.0"` |

---

## Rule 1 — Relative `.pow/assets` paths

**Detects:** paths that traverse up from the `.usda` file into the `.pow/assets/` directory using `../` segments.

```
Pattern: @../../.pow/assets/<subpath>@
```

The replacement depends on what `<subpath>` contains (checked in order):

| Subpath contains | Replacement target | Reason |
|:-----------------|:-------------------|:-------|
| `simready_content` | SimReady staging S3 URL | SimReady assets live on a separate staging bucket |
| `Pow` | `pow-assets` Omniverse alias | Custom pow-managed content |
| Anything else | NVIDIA production S3 URL | Standard Isaac Sim assets |

**Examples:**

```diff
# NVIDIA production asset
- @../../.pow/assets/Isaac/Robots/Carter/nova_carter.usd@
+ @https://omniverse-content-production.s3.us-west-2.amazonaws.com/Isaac/Robots/Carter/nova_carter.usd@

# SimReady asset
- @../../.pow/assets/simready_content/ForkliftC/ForkliftC.usd@
+ @https://omniverse-content-staging.s3.us-west-2.amazonaws.com/simready_content/ForkliftC/ForkliftC.usd@

# Pow custom asset
- @../../.pow/assets/Pow/MyRobot/robot.usd@
+ @pow-assets/Pow/MyRobot/robot.usd@
```

---

## Rule 2 — Absolute home directory paths

**Detects:** paths that start with the current user's absolute home directory (e.g. `/home/username/`).

```
Pattern: @/home/<username>/<rest>@
```

These are non-portable because the home path differs on every machine. The fix replaces the home prefix with the `user-home` alias, which is resolved at runtime per-machine.

**Example:**

```diff
- @/home/john/projects/sim-project/usda/warehouse.usd@
+ @user-home/projects/sim-project/usda/warehouse.usd@
```

> [!NOTE]
> The `user-home` alias is automatically configured in `~/.nvidia-omniverse/config/omniverse.toml` during `pow init`. It maps to the current user's home directory at runtime.

---

## Rule 3 — Relative ROS workspace paths

**Detects:** paths that traverse up with `../` segments to reach the ROS workspace directory specified as `isaacsim_ros_ws` in `pow.toml`. This commonly occurs when referencing robot USD/mesh models that live inside the ROS workspace.

```
Pattern: @../../../../<ros_ws_name>/<rest>@
         (where ros_ws_name comes from isaacsim_ros_ws in pow.toml)
```

**Example** (with `isaacsim_ros_ws = "~/IsaacSim-ros_workspaces"`):

```diff
- @../../../../IsaacSim-ros_workspaces/jazzy_ws/src/nova_carter/meshes/chassis.usd@
+ @user-home/IsaacSim-ros_workspaces/jazzy_ws/src/nova_carter/meshes/chassis.usd@
```

> [!NOTE]
> Rule 3 is only active when `isaacsim_ros_ws` is set in `pow.toml`. If the key is missing or `pow.toml` is not found, this rule is skipped.

---

## Rule 4 — Isaac asset version mismatch

**Detects:** asset references pointing at an `Assets/Isaac/<major>.<minor>` tree that is
not the one your project's Isaac Sim version reads from.

```
Pattern: @<anything>/Assets/Isaac/<major>.<minor>/<rest>@
         (compared against version in pow.toml [sim])
```

NVIDIA publishes the Isaac asset tree once per minor release — `Assets/Isaac/5.0`,
`5.1`, `6.0`, `6.1` — and every one of them stays online. A stage authored against 5.1 keeps
resolving after the project moves to 6.1.0, so nothing fails; it just quietly loads the
previous release's assets. This rule makes that visible.

The target uses verified release metadata from `version` in `pow.toml`, so `6.1.0` → `Assets/Isaac/6.1` and
`5.1.0` → `Assets/Isaac/5.1`. Unknown releases are not rewritten. It applies to every reference form: production S3 URLs,
`pow-assets` and `user-home` aliases, and still-relative paths.

**Example** (with `version = "6.1.0"`):

```diff
- @https://omniverse-content-production.s3.us-west-2.amazonaws.com/Assets/Isaac/5.0/Isaac/Robots/Carter/nova_carter.usd@
+ @https://omniverse-content-production.s3.us-west-2.amazonaws.com/Assets/Isaac/6.1/Isaac/Robots/Carter/nova_carter.usd@
```

Only the version segment is rewritten, and only inside an `@...@` reference — the same
text in a comment or a prim name is left alone. A reference that trips Rule 1 as well is
settled in the same `pow lint fix` run: it becomes the production S3 URL *and* the
configured version.

> [!NOTE]
> Rule 4 is only active when `version` is set in `pow.toml`. If the key is missing or
> `pow.toml` is not found, this rule is skipped.

Version-prefix fixes only change reference prefixes. They do not migrate renamed assets or application APIs. Scene changes require `pow lint fix`.
