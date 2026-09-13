try:
    import tomllib
except ImportError:
    import tomli as tomllib
import distro
import click
import platform
import re
from pathlib import Path
from typing import Any, Optional

class PowConfig:
    """Singleton class that provides project-wide configuration.

    Responsibilities:
    - Isaac Sim / ROS constants (class-level).
    - Global directory paths (home, global_path) – always available.
    - pow.toml project settings – available only when a pow.toml is found.
    """

    _instance = None

    # ── Isaac Sim constants ───────────────────────────────────────────────────

    #: Installable Isaac Sim releases, keyed by version.  **Ordered latest
    #: first** - the default version, the version picker, and the auto-detected
    #: ``pow sim -v`` all read "newest" as the first entry.
    #: ``downloads`` maps each host architecture to its build.  URLs are
    #: deliberately spelled out per release and architecture: 6.1.0 is served
    #: from a different host than 5.1.0, so the download location cannot be
    #: derived from the version string.  A release without an entry for an
    #: architecture is not installable there.
    ISAACSIM_RELEASES: dict[str, dict[str, Any]] = {
        "6.1.0": {
            "downloads": {
                "x86_64": "https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-linux-x86_64.zip",
                "aarch64": "https://downloads.isaacsim.nvidia.com/isaac-sim-standalone-6.1.0-linux-aarch64.zip",
            },
            "ros_ws_ref": "IsaacSim-6.1.0",
            "ros_ws_commit": "a9e8471ee901bc2332c1e4aca94ac580713ca3ab",
            "asset_version": "6.1",
        },
        "5.1.0": {
            "downloads": {
                "x86_64": (
                    "https://download.isaacsim.omniverse.nvidia.com/"
                    "isaac-sim-standalone-5.1.0-linux-x86_64.zip"
                ),
                "aarch64": (
                    "https://download.isaacsim.omniverse.nvidia.com/"
                    "isaac-sim-standalone-5.1.0-linux-aarch64.zip"
                ),
            },
            "ros_ws_ref": "IsaacSim-5.1.0",
            "asset_version": "5.1",
        },
    }
    SUPPORTED_ISAACSIM_VERSIONS = tuple(ISAACSIM_RELEASES)
    ISAACSIM_VERSION = SUPPORTED_ISAACSIM_VERSIONS[0]
    SUPPORTED_UBUNTU_VERSIONS = ["22.04", "24.04"]

    #: Host architectures pow can install and launch Isaac Sim on.  NVIDIA
    #: supports the aarch64 builds on DGX Spark only.
    SUPPORTED_ARCHITECTURES = ("x86_64", "aarch64")

    #: ``platform.machine()`` spellings that name the same architecture.
    _ARCH_ALIASES = {"amd64": "x86_64", "arm64": "aarch64"}

    #: A version is used as a single path component under ``<global>/isaacsim/``.
    #: Anything outside this shape could escape that directory.
    _VERSION_COMPONENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

    # ── ROS constants ────────────────────────────────────────────────────────

    ROS_DISTRO = "jazzy"
    ROS_BRIDGE = "jazzy"
    SUPPORTED_ROS_BRIDGES = ("humble", "jazzy")

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(PowConfig, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        # ── Global / home paths (always available) ────────────────────────────
        self._global_dir_name: str = self._read_global_dir_name()
        self._home: Path = Path.home()
        self._global_path: Path = self._home / self._global_dir_name

        # ── Project config (requires pow.toml) ───────────────────────────────
        self._project_root: Optional[Path] = self._find_project_root()
        self._data: dict[str, Any] = {}

        if self._project_root:
            self._load_config(self._project_root)

    @staticmethod
    def _read_global_dir_name(start_path: Optional[Path] = None) -> str:
        """Read global_dir_name from pyproject.toml or default to .pow"""
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()

        while True:
            pyproject_path = current / "pyproject.toml"
            if pyproject_path.exists():
                with open(pyproject_path, "rb") as f:
                    try:
                        data = tomllib.load(f)
                        val = data.get("tool", {}).get("pow-cli", {}).get("global_dir_name")
                        if val:
                            return val
                    except Exception:
                        pass
                break # Found pyproject.toml but no valid global_dir_name, use default
            
            if current == current.parent:
                break
            current = current.parent

        return ".pow"

    @classmethod
    def resolve_global_path(cls) -> Path:
        """Absolute path to the global pow directory, without loading pow.toml.

        Honors ``[tool.pow-cli] global_dir_name`` from a pyproject.toml above
        cwd when present, otherwise ``~/.pow``.  Used by ``pow sim``, which must
        work in directories that are not pow projects.
        """
        return Path.home() / cls._read_global_dir_name()

    # ── Isaac Sim version helpers ────────────────────────────────────────────

    @classmethod
    def host_arch(cls) -> str:
        """The host CPU architecture, normalized (``amd64`` → ``x86_64``, ``arm64`` → ``aarch64``)."""
        machine = platform.machine().lower()
        return cls._ARCH_ALIASES.get(machine, machine)

    @classmethod
    def versions_for_arch(cls, arch: Optional[str] = None) -> tuple[str, ...]:
        """Supported versions with a build for *arch* (default: the host), latest first."""
        arch = arch or cls.host_arch()
        return tuple(
            version for version, release in cls.ISAACSIM_RELEASES.items()
            if arch in release["downloads"]
        )

    @classmethod
    def release(cls, version: str, arch: Optional[str] = None) -> dict[str, str]:
        """Return download metadata for *version* on *arch* (default: the host), or raise.

        This is the allowlist gate for installs: the download URL is only ever
        read out of :attr:`ISAACSIM_RELEASES`, never built from a version
        string supplied on the command line or read from pow.toml.  The result
        carries the ``url`` and ``filename`` of the build for *arch*.
        """
        try:
            release = cls.ISAACSIM_RELEASES[str(version).strip()]
        except KeyError:
            raise click.ClickException(
                f"Unsupported Isaac Sim version '{version}'. "
                f"Supported versions: {', '.join(cls.SUPPORTED_ISAACSIM_VERSIONS)}."
            ) from None

        arch = arch or cls.host_arch()
        url = release["downloads"].get(arch)
        if url is None:
            available = cls.versions_for_arch(arch)
            raise click.ClickException(
                f"Isaac Sim {version} has no linux-{arch} build. "
                f"Available on {arch}: {', '.join(available) if available else 'none'}."
            )

        metadata = {key: value for key, value in release.items() if key != "downloads"}
        return {**metadata, "url": url, "filename": url.rsplit("/", 1)[-1]}

    @classmethod
    def version_dir(cls, version: str, global_path: Optional[Path] = None) -> Path:
        """Resolve ``<global_path>/isaacsim/<version>`` safely.

        Unlike :meth:`release` this accepts any well-formed version, so a
        manually placed install still works with ``pow sim -v``.  It only
        rejects values that would not be a single directory name (``..``,
        embedded separators, absolute paths).
        """
        name = str(version).strip()
        if not cls._VERSION_COMPONENT_RE.match(name):
            raise click.ClickException(
                f"Invalid Isaac Sim version '{version}'. "
                "A version may only contain letters, digits, '.', '_' and '-'."
            )
        base = cls.resolve_global_path() if global_path is None else global_path
        return base / "isaacsim" / name

    @classmethod
    def installed_versions(cls, global_path: Optional[Path] = None) -> list[str]:
        """List Isaac Sim versions installed under ``<global_path>/isaacsim``.

        A directory counts as installed only when it holds ``isaac-sim.sh``, so
        a leftover partial extraction is not mistaken for a usable install.
        Known releases sort first (latest to oldest), unknown ones after.
        """
        base = cls.resolve_global_path() if global_path is None else global_path
        isaacsim_dir = base / "isaacsim"
        try:
            found = [
                d.name for d in isaacsim_dir.iterdir()
                if d.is_dir() and (d / "isaac-sim.sh").exists()
            ]
        except OSError:
            return []

        known = [v for v in cls.SUPPORTED_ISAACSIM_VERSIONS if v in found]
        # Unknown versions also sort descending, so the whole list stays
        # latest-first and callers can just take the head.
        unknown = sorted(set(found) - set(known), reverse=True)
        return known + unknown

    @classmethod
    def configured_default_version(cls, global_path: Optional[Path] = None) -> str:
        """``[sim] default_version`` from system.toml, or "" when unset.

        A missing, unreadable or malformed system.toml must never break
        ``pow sim``, so every failure reads as "no preference configured".
        """
        from .system_config import SystemConfig

        base = cls.resolve_global_path() if global_path is None else global_path
        path = base / "system.toml"
        try:
            return SystemConfig.from_file(path).sim.default_version
        except (OSError, tomllib.TOMLDecodeError):
            return ""

    @classmethod
    def resolve_installed_version(cls, global_path: Optional[Path] = None) -> str:
        """Default Isaac Sim version for commands that take ``-v``.

        Prefers what is actually installed - the sole install when there is
        one, otherwise the newest known release present - so ``pow sim`` works
        without ``-v`` for users who installed a non-default version.  Falls
        back to :attr:`ISAACSIM_VERSION` when nothing is installed.
        """
        installed = cls.installed_versions(global_path)
        if not installed:
            return cls.ISAACSIM_VERSION
        known = [v for v in installed if v in cls.ISAACSIM_RELEASES]
        return known[0] if known else installed[0]

    def _find_project_root(self, start_path: Optional[Path] = None) -> Optional[Path]:
        """Find the project root by locating pow.toml."""
        if start_path is None:
            start_path = Path.cwd()

        current = start_path.resolve()

        while current != current.parent:
            if (current / "pow.toml").exists():
                return current
            current = current.parent

        if (current / "pow.toml").exists():
            return current

        return None

    def _load_config(self, project_root: Path) -> None:
        """Load pow.toml configuration into memory.

        A pow.toml that is not valid TOML is reported as a plain error rather
        than a tomllib traceback: every command goes through here, and the file
        is the user's to fix - pow never rewrites it to make it parse.
        """
        config_path = project_root / "pow.toml"
        if not config_path.exists():
            return

        with open(config_path, "rb") as f:
            try:
                self._data = tomllib.load(f)
            except tomllib.TOMLDecodeError as e:
                raise click.ClickException(
                    f"{config_path} is not valid TOML: {e}\n"
                    "Fix it, or delete it and re-run `pow init`."
                ) from e

    # ── Global / home path properties ────────────────────────────────────────

    @property
    def global_dir_name(self) -> str:
        """The name of the global pow directory (e.g. '.pow')."""
        return self._global_dir_name

    @property
    def home(self) -> Path:
        """The current user's home directory."""
        return self._home

    @property
    def global_path(self) -> Path:
        """Absolute path to the global pow directory (e.g. ~/.pow)."""
        return self._global_path

    @property
    def ros_ws_path(self) -> Path:
        """Absolute path to the ROS workspaces directory.

        Reads ``isaacsim_ros_ws`` from pow.toml ``[sim]``.  The value is
        stored as a tilde-relative string (e.g. ``~/IsaacSim-ros_workspaces``)
        and expanded to an absolute path here.  Falls back to
        ``~/IsaacSim-ros_workspaces`` when the key is missing or pow.toml
        is not loaded.
        """
        default = "~/IsaacSim-ros_workspaces"
        try:
            raw = self.get("isaacsim_ros_ws", default)
        except RuntimeError:
            raw = default
        return Path(raw).expanduser()

    @property
    def ros_dockerfile(self) -> str:
        """Relative path to a custom ROS Dockerfile, or "" if unset.

        Reads ``ros_dockerfile`` from pow.toml ``[sim]``.  When set, the custom
        Dockerfile is built on top of the bundled ``pow_simros_<distro>`` base
        image during ``pow init``.  Falls back to an empty string when the key
        is missing or pow.toml is not loaded.
        """
        try:
            return self.get("ros_dockerfile", "") or ""
        except RuntimeError:
            return ""

    @property
    def ros_docker_image(self) -> str:
        """Docker image name for the ROS image.

        Reads ``ros_docker_image`` from pow.toml ``[sim]``.  Used as the image
        tag when ``ros_dockerfile`` is set.  Defaults to ``"pow_simros"`` when
        the key is missing or pow.toml is not loaded.
        """
        try:
            return self.get("ros_docker_image", "pow_simros") or "pow_simros"
        except RuntimeError:
            return "pow_simros"

    @property
    def ros_image_name(self) -> str:
        """Image to run with ``pow ros``.

        Returns the custom ``ros_docker_image`` tag when ``ros_dockerfile`` is
        set, otherwise the bundled ``pow_simros_<distro>`` base image.
        """
        if self.ros_dockerfile:
            return self.ros_docker_image
        return f"pow_simros_{self.ros_distro}"

    @property
    def ros_container_name(self) -> str:
        """Container name derived from ``ros_image_name``.

        Docker container names must match ``[a-zA-Z0-9][a-zA-Z0-9_.-]*``, so
        characters like ``/`` and ``:`` in the image reference are replaced
        with ``_``.
        """
        name = re.sub(r"[^a-zA-Z0-9_.-]", "_", self.ros_image_name)
        name = re.sub(r"^[^a-zA-Z0-9]+", "", name)
        return name or "pow_simros"

    @property
    def ros_distro(self) -> str:
        """ROS 2 distribution used for the ROS workspace and docker image.

        Only jazzy is supported (buildable on Ubuntu 22.04 and 24.04 hosts).
        """
        return self.ROS_DISTRO

    @property
    def ros_bridge(self) -> str:
        """ROS distro of the Isaac Sim internal ROS2 bridge (default profile).

        Reads ``ros_bridge`` from pow.toml ``[sim]`` and selects which
        prebuilt bridge libs under ``exts/isaacsim.ros2.core|bridge/<distro>/lib``
        Isaac Sim loads. Defaults to ``"jazzy"`` when the key is missing or
        pow.toml is not loaded. Use :meth:`get_ros_bridge` to resolve
        the value for a specific profile.
        """
        return self.get_ros_bridge()

    def get_ros_bridge(self, profile: str = "default") -> str:
        """Resolve the ROS bridge distro for *profile*, validated.

        Reads ``ros_bridge`` from the resolved *profile* (so a
        ``[[profiles]]`` entry can override it), falling back to ``"jazzy"``
        when the key is missing or pow.toml is not loaded. The value must be
        one of :attr:`SUPPORTED_ROS_BRIDGES`.
        """
        try:
            value = self.get(
                "ros_bridge", self.ROS_BRIDGE, profile=profile
            ) or self.ROS_BRIDGE
        except RuntimeError:
            value = self.ROS_BRIDGE
        value = str(value).strip().lower()
        if value not in self.SUPPORTED_ROS_BRIDGES:
            raise click.ClickException(
                f"Invalid ros_bridge '{value}' in pow.toml. "
                f"Supported values: {', '.join(self.SUPPORTED_ROS_BRIDGES)}."
            )
        return value

    @property
    def ubuntu_version(self) -> str:
        """Get the current Ubuntu version or fallback to 22.04."""
        try:
            v = distro.version()
            if v in self.SUPPORTED_UBUNTU_VERSIONS:
                return v
        except Exception:
            pass
        return "22.04"

    # ── Project config properties ────────────────────────────────────────────

    @property
    def project_root(self) -> Optional[Path]:
        """Get the project root directory, or None if pow.toml was not found."""
        return self._project_root

    @property
    def data(self) -> dict[str, Any]:
        """Get the complete parsed data from pow.toml.

        Raises RuntimeError if pow.toml was not found during initialization.
        """
        self._require_project()
        return self._data

    def get_profile(self, profile_name: str = "default") -> dict[str, Any]:
        """
        Get a merged profile dictionary with ``extends`` and ``.add`` support.

        Resolution order
        ----------------
        1. If *profile_name* is ``"default"`` or ``"sim"``, return ``[sim]`` data.
        2. Otherwise locate the ``[[profiles]]`` entry whose ``name`` matches.
        3. Determine the *base* config:
           - No ``extends`` key, or ``extends = "default"`` → ``[sim]``
           - ``extends = "<other>"`` → recursively resolve that profile first.
             Circular references and missing targets raise ``ClickException``.
        4. Apply ``.add`` append keys: a key like ``exts.add`` appends its list
           value to the base ``exts`` list.  If the base value is not a list a
           ``ClickException`` is raised immediately (fail-fast at ``pow run``).
        5. Strip ``name``, ``extends``, and all ``*.add`` keys from the result.

        Raises
        ------
        RuntimeError
            If pow.toml was not found during initialization.
        click.ClickException
            If ``extends`` is circular, targets a missing profile, or a ``.add``
            key targets a non-list base value.
        """
        self._require_project()
        return self._resolve_profile(profile_name, _seen=set())

    def _resolve_profile(
        self,
        profile_name: str,
        _seen: "set[str]",
    ) -> "dict[str, Any]":
        """Internal recursive resolver for ``get_profile``."""
        import copy

        sim_data: dict[str, Any] = copy.deepcopy(self._data.get("sim", {}))

        if profile_name in ("default", "sim"):
            return sim_data

        profiles: list[dict[str, Any]] = self._data.get("profiles", [])
        target: dict[str, Any] | None = next(
            (p for p in profiles if p.get("name") == profile_name), None
        )
        if target is None:
            raise click.ClickException(
                f"Profile '{profile_name}' not found in pow.toml [[profiles]]."
            )

        extends: str = target.get("extends", "default")

        # ── Circular-extends guard ────────────────────────────────────────────
        if profile_name in _seen:
            cycle = " → ".join(sorted(_seen)) + f" → {profile_name}"
            raise click.ClickException(
                f"Circular 'extends' detected in pow.toml profiles: {cycle}"
            )
        _seen = _seen | {profile_name}

        # ── Resolve base ──────────────────────────────────────────────────────
        if extends in ("default", "sim"):
            base: dict[str, Any] = sim_data
        else:
            base = self._resolve_profile(extends, _seen)

        # ── Apply overrides and .add append keys ──────────────────────────────
        merged = dict(base)

        # TOML parses `exts.add = [...]` as {"exts": {"add": [...]}} (dotted keys
        # create nested dicts rather than literal string keys).  Flatten those so
        # the rest of the logic can treat them uniformly as "exts.add" string keys.
        flat_target: dict[str, Any] = {}
        for key, value in target.items():
            if (
                isinstance(value, dict)
                and list(value.keys()) == ["add"]
                and isinstance(value["add"], list)
            ):
                flat_target[f"{key}.add"] = value["add"]
            else:
                flat_target[key] = value

        # First pass: plain overrides (skip meta-keys and *.add keys)
        for key, value in flat_target.items():
            if key in ("name", "extends"):
                continue
            if key.endswith(".add"):
                continue
            merged[key] = value

        # Second pass: .add append keys
        for key, value in flat_target.items():
            if not key.endswith(".add"):
                continue
            root_key = key[: -len(".add")]
            base_value = merged.get(root_key)
            if base_value is None:
                # Key doesn't exist in base yet – treat as a plain list assignment
                merged[root_key] = list(value) if isinstance(value, list) else [value]
            elif not isinstance(base_value, list):
                raise click.ClickException(
                    f"Profile '{profile_name}': '{key}' targets '{root_key}' which is "
                    f"not a list (got {type(base_value).__name__}). "
                    "The '.add' append keyword only works with list values."
                )
            else:
                if not isinstance(value, list):
                    raise click.ClickException(
                        f"Profile '{profile_name}': '{key}' value must be a list, "
                        f"got {type(value).__name__}."
                    )
                merged[root_key] = base_value + value

        return merged


    def get(self, key: str, default: Any = None, profile: str = "default") -> Any:
        """
        Get a specific setting from pow.toml, defaulting to the '[sim]' profile.

        Args:
            key: The setting key to fetch.
            default: The default value if the key does not exist.
            profile: The profile name to look in, defaults to 'default' (which maps to [sim]).

        Raises RuntimeError if pow.toml was not found.
        """
        profile_data = self.get_profile(profile)
        return profile_data.get(key, default)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _require_project(self) -> None:
        """Raise RuntimeError if no pow.toml was found during initialization."""
        if self._project_root is None:
            raise RuntimeError("Project not initialized: pow.toml not found")
