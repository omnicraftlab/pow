"""Manager core logic."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import zipfile
import urllib.request
from pathlib import Path

import distro
import tomlkit

from . import vscode_settings
from .models.pow_config import PowConfig
from .models.system_config import SystemConfig


class Initializer:
    """Handles the management and initialization process for Isaac Powerpack.
    
    This class is responsible for:
    - Initialize project and global directory.
    - download isaacsim and fix its initial issues
    - setup isaacsim ros workspace
    """

    GLOBAL_SUBFOLDERS = ("isaacsim", "modules", "projects", "sim-ros")

    def __init__(self, global_path: Path | None = None):
        """Optionally use a global path without loading project configuration."""
        self._config_instance = None
        self._global_path = global_path

    @property
    def global_path(self) -> Path:
        """Global setup location; an override never loads pow.toml."""
        return self._global_path if self._global_path is not None else self.config.global_path

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _check_platform(self):
        """Raise RuntimeError when the current platform cannot run Isaac Sim."""
        if PowConfig.host_arch() not in PowConfig.SUPPORTED_ARCHITECTURES:
            raise RuntimeError(
                f"Unsupported architecture: {platform.machine()}. "
                "Isaac Sim requires x86_64 or aarch64."
            )

        system = platform.system()
        if system in ("Windows", "Darwin"):
            label = "Windows" if system == "Windows" else "macOS"
            raise RuntimeError(
                f"Unsupported OS: {label}. Pow only support Isaac Sim on Ubuntu 22.04 or 24.04."
            )
        if system != "Linux":
            raise RuntimeError(
                f"Unsupported OS: {system}. Pow only support Isaac Sim on Ubuntu 22.04 or 24.04."
            )

        try:
            distro_id = distro.id()
            distro_version = distro.version()
            if distro_id != "ubuntu" or distro_version not in PowConfig.SUPPORTED_UBUNTU_VERSIONS:
                distro_name = distro.name()
                raise RuntimeError(
                    f"Unsupported OS: {distro_name} {distro_version}. "
                    f"Isaac Sim requires Ubuntu 22.04 or 24.04."
                )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(f"Could not verify OS version using distro package: {e}")


    @staticmethod
    def _data_path(filename: str) -> Path:
        return Path(__file__).parent.parent / "data" / filename

    def _configured_version(self) -> str:
        """Isaac Sim version from pow.toml, or the default when unavailable."""
        if self._global_path is not None:
            return PowConfig.ISAACSIM_VERSION
        try:
            return self.config.get("version", PowConfig.ISAACSIM_VERSION)
        except Exception:
            return PowConfig.ISAACSIM_VERSION

    # ── Public API ────────────────────────────────────────────────────────────

    def get_config_path(self):
        """Return global configuration information for Step 1."""
        return {
            "global_dir_name": (
                self._global_path.name
                if self._global_path is not None else self.config.global_dir_name
            ),
            "global_path": self.global_path,
        }

    def get_config(self) -> PowConfig:
        """Get the PowConfig object representing pow.toml."""
        return self.config

    def get_isaacsim_path(self, version: str | None = None) -> Path | None:
        """Resolve the Isaac Sim installation path.

        Checks the managed .pow/isaacsim/<version> folder first, then falls
        back to matching ``isaacsim`` distribution metadata. Returns None if
        Isaac Sim cannot be located.

        Args:
            version: Isaac Sim version to look for.  Defaults to the version
                     in pow.toml, then to :attr:`PowConfig.ISAACSIM_VERSION`.
        """
        managed = PowConfig.version_dir(
            version or self._configured_version(), self.global_path
        )
        if managed.is_dir():
            return managed

        # Inspect distribution metadata without importing Isaac Sim (which can
        # initialize its runtime). A different installed version is not a fallback.
        from importlib.metadata import distribution, PackageNotFoundError
        try:
            dist = distribution("isaacsim")
            requested = version or self._configured_version()
            if dist.version in (requested, requested + ".0"):
                pkg_path = Path(dist.locate_file("isaacsim"))
                if (pkg_path / "isaac-sim.sh").is_file():
                    return pkg_path
        except PackageNotFoundError:
            pass

        return None



    def create_global_folder(self):
        """Create the global directories and return the created paths with status."""
        global_path = self.global_path
        global_dir_name = self.get_config_path()["global_dir_name"]

        global_exists = global_path.is_dir()
        if not global_exists:
            global_path.mkdir(parents=True)

        results = []
        for sub in self.GLOBAL_SUBFOLDERS:
            sub_path = global_path / sub
            existed = sub_path.is_dir()
            if not existed:
                sub_path.mkdir(parents=True, exist_ok=True)
            results.append({
                "path": f"{global_dir_name}/{sub}",
                "status": "Existed" if existed else "Created",
            })

        return {"global_existed": global_exists, "results": results}

    def create_system_toml(self) -> dict:
        """Create system.toml in the global folder if it does not already exist."""
        system_toml_path = self.global_path / "system.toml"
        if system_toml_path.is_file():
            return {"status": "Existed", "path": str(system_toml_path)}
        if system_toml_path.exists() or system_toml_path.is_symlink():
            raise RuntimeError(f"Expected a configuration file at {system_toml_path}.")

        system_config = SystemConfig.default()
        doc = tomlkit.document()
        for section, values in system_config.to_dict().items():
            table = tomlkit.table()
            for k, v in values.items():
                table.add(k, v)
            doc.add(section, table)
        system_toml_path.write_text(tomlkit.dumps(doc))
        return {"status": "Created", "path": str(system_toml_path)}

    @property
    def config(self) -> PowConfig:
        """Get the PowConfig singleton, instantiating it efficiently."""
        if self._config_instance is None:
            self._config_instance = PowConfig()
        return self._config_instance

    def read_config(self):
        """Read configuration from an existing pow.toml file using the PowConfig singleton."""
        return self.config.data

    @staticmethod
    def asset_browser_cache_path(isaacsim_path: Path) -> Path:
        return (
            Path(isaacsim_path)
            / "exts"
            / "isaacsim.asset.browser"
            / "cache"
            / "isaacsim.asset.browser.cache.json"
        )

    def fix_asset_browser_cache(self, isaacsim_path) -> bool:
        """Create the missing asset browser cache, preserving existing files."""
        cache_path = self.asset_browser_cache_path(isaacsim_path)
        if cache_path.is_file():
            return False
        if cache_path.exists() or cache_path.is_symlink():
            raise RuntimeError(f"Expected an asset browser cache file at {cache_path}.")
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "x") as f:
            json.dump({}, f, indent=4)
        return True

    @staticmethod
    def isaacsim_ready(isaacsim_path: Path, *, check: bool = False) -> bool:
        """Check the entry points needed by the requested sim command."""
        return (isaacsim_path / "isaac-sim.sh").is_file() and (
            not check or (isaacsim_path / "isaac-sim.compatibility_check.sh").is_file()
        )

    def download_isaacsim(
        self,
        version: str | None = None,
        progress_callback=None,
        status_callback=None,
        mock=False,
        *,
        check: bool = False,
    ):
        """Download and install Isaac Sim.

        Args:
            version: Version to install.  Must be one of
                     :attr:`PowConfig.SUPPORTED_ISAACSIM_VERSIONS`; defaults to
                     :attr:`PowConfig.ISAACSIM_VERSION`.
            check: Also require the compatibility check script.

        Incomplete installations are backed up outside the installed-version
        scan. A failed or interrupted repair restores the original contents.
        """
        self._check_platform()

        version = version or PowConfig.ISAACSIM_VERSION
        target_folder = PowConfig.version_dir(version, self.global_path)
        if not mock and self.isaacsim_ready(target_folder, check=check):
            return {"status": "Already installed", "path": str(target_folder), "version": version}

        release = PowConfig.release(version)

        dest_dir = self.global_path / "isaacsim"
        dest_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dest_dir / release["filename"]
        self._download_isaacsim_zip(
            release["url"], zip_path, progress_callback, status_callback, mock
        )

        backup = None
        if not mock and (target_folder.exists() or target_folder.is_symlink()):
            backups = self.global_path / "isaacsim-backups"
            backups.mkdir(parents=True, exist_ok=True)
            backup = Path(tempfile.mkdtemp(prefix=f"{version}-", dir=backups)) / version
            try:
                target_folder.rename(backup)
            except BaseException:
                backup.parent.rmdir()
                raise

        try:
            self._extract_isaacsim_zip(
                zip_path, target_folder, progress_callback, status_callback, mock
            )
            if not mock and not self.isaacsim_ready(target_folder, check=check):
                raise RuntimeError(
                    f"Isaac Sim installation at {target_folder} is missing required scripts."
                )
        except BaseException:
            # Only remove this attempt's extraction; the original is in backup.
            if not mock:
                if target_folder.is_symlink() or target_folder.is_file():
                    target_folder.unlink()
                elif target_folder.exists():
                    shutil.rmtree(target_folder)
                if backup is not None:
                    backup.rename(target_folder)
                    backup.parent.rmdir()
            raise

        result = {
            "status": "Downloaded and installed", "path": str(target_folder), "version": version,
        }
        if backup is not None:
            result["backup"] = str(backup)
        return result

    def setup_project_structure(self, local_folders: list) -> dict:
        """Create project folders and .gitignore from template."""
        results = []

        for folder in local_folders:
            path = Path(folder)
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                results.append({"path": folder, "status": "Created"})
            else:
                results.append({"path": folder, "status": "Existed"})

        gitignore_path = Path(".gitignore")
        template_path = self._data_path("gitignore.template")

        if gitignore_path.exists():
            results.append({"path": ".gitignore", "status": "Existed"})
        elif template_path.exists():
            shutil.copy(template_path, gitignore_path)
            results.append({"path": ".gitignore", "status": "Created from template"})
        else:
            results.append({"path": ".gitignore", "status": "Template not found"})

        return {"results": results}

    def link_managed_isaacsim(self, version: str | None = None) -> dict:
        """Symlink global managed Isaac Sim to project's _isaacsim.

        Re-points an existing symlink when it does not already resolve to
        *version*, so switching versions with ``pow init`` does not leave the
        project pointing at the previous install.  A real file or directory at
        ``_isaacsim`` is never deleted - that would destroy data the user may
        have put there deliberately - and is reported as an error instead.
        """
        version = version or self._configured_version()
        global_isaacsim = PowConfig.version_dir(version, self.global_path)

        if not global_isaacsim.is_dir():
            return {"status": "Error", "message": f"Global Isaac Sim {version} not found."}

        target_link = Path("_isaacsim")

        if target_link.is_symlink():
            current = target_link.readlink()
            if current == global_isaacsim:
                return {"status": "Existed", "path": str(target_link)}
            target_link.unlink()
            target_link.symlink_to(global_isaacsim, target_is_directory=True)
            return {"status": "Repointed", "path": str(target_link), "previous": str(current)}

        if target_link.exists():
            return {
                "status": "Error",
                "message": (
                    f"'{target_link}' exists and is not a symlink. "
                    "Remove or rename it, then re-run `pow init`."
                ),
            }

        target_link.symlink_to(global_isaacsim, target_is_directory=True)
        return {"status": "Created", "path": str(target_link)}

    def setup_vscode_configs(
        self, version: str | None = None, version_changed: bool = True
    ) -> dict:
        """Set up the project's .vscode configs from a specific Isaac Sim install.

        ``launch.json``, ``tasks.json`` and ``c_cpp_properties.json`` are copied
        over, with ``${workspaceFolder}`` re-pointed at ``_isaacsim``.
        ``settings.json`` is **merged** instead - see
        :mod:`pow_cli.core.vscode_settings` - so the settings a user added to it
        survive a re-run of init.

        Args:
            version: the Isaac Sim version to configure for.  Defaults to the
                version in pow.toml.  The configs are read from that install
                rather than from wherever ``_isaacsim`` happens to point, so the
                extension paths always belong to the version init selected.
            version_changed: whether init just moved the project to a different
                Isaac Sim version.  Only then is ``python.analysis.extraPaths``
                rewritten; otherwise the project keeps the list it has.
        """
        version = version or self._configured_version()
        isaacsim_path = self.get_isaacsim_path(version)
        if isaacsim_path is None:
            return {"status": "Error", "message": f"Isaac Sim {version} not found."}

        # The paths written into settings.json are relative to _isaacsim, so they
        # are only correct while that symlink resolves to the install they came
        # from.  Writing them against a stale link is the wrong-version bug.
        link = Path("_isaacsim")
        try:
            linked_at = link.resolve(strict=True)
        except OSError:
            return {"status": "Error", "message": "_isaacsim not found."}
        if linked_at != isaacsim_path.resolve():
            return {
                "status": "Error",
                "message": (
                    f"'_isaacsim' points at {linked_at}, not at Isaac Sim {version} "
                    f"({isaacsim_path}).  Re-run `pow init` to re-link it."
                ),
            }

        src_vscode = isaacsim_path / ".vscode"
        dest_vscode = Path(".vscode")

        if not src_vscode.is_dir():
            return {
                "status": "Error",
                "message": f"{src_vscode} not found.",
            }

        dest_vscode.mkdir(parents=True, exist_ok=True)
        files_to_copy = ["launch.json", "tasks.json", "c_cpp_properties.json"]
        patch_files = {"launch.json", "tasks.json"}
        results = []

        for filename in files_to_copy:
            src_file = src_vscode / filename
            dest_file = dest_vscode / filename

            if not src_file.exists():
                results.append({"file": filename, "status": "Not found in source"})
                continue

            shutil.copy(src_file, dest_file)

            if filename not in patch_files:
                results.append({"file": filename, "status": "Copied"})
                continue

            # Patch: replace ${workspaceFolder} with _isaacsim
            content = dest_file.read_text().replace("${workspaceFolder}", "_isaacsim")
            dest_file.write_text(content)
            results.append({"file": filename, "status": "Copied and patched"})

        settings_result = vscode_settings.apply(
            dest_vscode / "settings.json",
            src_vscode / "settings.json",
            replace_extra_paths=version_changed,
        )
        results.append({"file": "settings.json", **settings_result})

        return {"status": "Success", "results": results, "version": version}

    def init_git(self) -> dict:
        """Initialize git repository if it doesn't already exist."""
        git_dir = Path(".git")
        if git_dir.exists():
            return {"status": "Existed"}

        try:
            subprocess.run(["git", "init", "--quiet"], check=True)
            return {"status": "Created"}
        except Exception as e:
            return {"status": "Error", "message": str(e)}

    def create_pow_toml(
        self,
        override: bool = False,
        enable_ros: bool = False,
        isaacsim_ros_ws: str = "~/IsaacSim-ros_workspaces",
        sim_version: str | None = None,
    ) -> dict:
        """Write the settings init collected into pow.toml.

        A missing pow.toml is created from the template.  An existing one is
        either left alone (``override=False``) or **patched in place** - only the
        keys init actually asked about are rewritten, so custom settings,
        ``[[profiles]]`` and comments survive.  A pow.toml that cannot be parsed
        is never written to; the caller reports the error and the file stays
        exactly as the user left it.

        Returns:
            ``status`` is one of ``Created``, ``Updated``, ``Existed``,
            ``Template not found`` or ``Error``.  ``Created``/``Updated`` also
            carry ``changed`` - see :meth:`_patch_pow_toml`.
        """
        # Initialize git if not already done
        self.init_git()

        pow_toml_path = Path("pow.toml")

        if pow_toml_path.exists():
            if not override:
                return {"status": "Existed", "path": str(pow_toml_path)}
            try:
                changed = self._patch_pow_toml(
                    pow_toml_path,
                    enable_ros=enable_ros,
                    isaacsim_ros_ws=isaacsim_ros_ws,
                    sim_version=sim_version,
                )
            except tomlkit.exceptions.ParseError as e:
                return {
                    "status": "Error",
                    "path": str(pow_toml_path),
                    "message": str(e),
                }
            return {
                "status": "Updated",
                "path": str(pow_toml_path),
                "changed": changed,
            }

        template_path = self._data_path("pow.template.toml")
        if not template_path.exists():
            return {"status": "Template not found", "path": str(pow_toml_path)}

        shutil.copy(template_path, pow_toml_path)
        changed = self._patch_pow_toml(
            pow_toml_path,
            enable_ros=enable_ros,
            isaacsim_ros_ws=isaacsim_ros_ws,
            sim_version=sim_version,
        )

        return {
            "status": "Created",
            "path": str(pow_toml_path),
            "changed": changed,
        }

    # ── Private methods ─────────────────────────────────────────────────────────

    @staticmethod
    def _fix_isaacsim_permissions(isaacsim_path: Path):
        """Recursively fix execute permissions lost during zip extraction.

        Makes all .sh files executable and restores execute bits on known
        binary paths (e.g. kit/python/bin/python3).
        """
        # Fix all .sh scripts
        for sh_file in isaacsim_path.rglob("*.sh"):
            if sh_file.is_file() and not os.access(sh_file, os.X_OK):
                sh_file.chmod(sh_file.stat().st_mode | 0o111)

        # Fix known binary directories
        bin_dirs = [
            isaacsim_path / "kit" / "python" / "bin",
            isaacsim_path / "kit",
        ]
        for bin_dir in bin_dirs:
            if not bin_dir.is_dir():
                continue
            for f in bin_dir.iterdir():
                if f.is_file() and not os.access(f, os.X_OK):
                    # Check if it looks like an ELF binary or script
                    try:
                        with open(f, "rb") as fh:
                            header = fh.read(4)
                        if header[:4] == b"\x7fELF" or header[:2] == b"#!":
                            f.chmod(f.stat().st_mode | 0o111)
                    except OSError:
                        pass

    def _download_isaacsim_zip(self, url, zip_path, progress_callback, status_callback, mock):
        """Download the Isaac Sim zip archive.

        Downloads to ``<name>.part`` and renames on success, so a run
        interrupted part-way through a multi-gigabyte download never leaves a
        truncated file that the next run would mistake for a complete archive.
        """
        if not mock and zip_path.exists():
            if status_callback:
                status_callback("Skipped download")
            return

        if status_callback:
            status_callback("Downloading")

        if mock:
            import time
            total_size = 100 * 1024 * 1024  # 100 MB mock
            for i in range(101):
                if progress_callback:
                    progress_callback(i * 1024 * 1024, total_size)
                time.sleep(0.02)
        else:
            def reporthook(blocknum, blocksize, totalsize):
                if progress_callback:
                    progress_callback(blocknum * blocksize, totalsize)

            part_path = zip_path.with_name(zip_path.name + ".part")
            try:
                urllib.request.urlretrieve(url, part_path, reporthook)
                os.replace(part_path, zip_path)
            except Exception as e:
                part_path.unlink(missing_ok=True)
                raise RuntimeError(f"Download failed: {e}")

    def _extract_isaacsim_zip(self, zip_path, target_folder, progress_callback, status_callback, mock):
        """Extract the Isaac Sim zip archive."""
        if mock:
            import time
            total_mock_files = 100
            if status_callback:
                status_callback("Extracting")
            for i in range(total_mock_files + 1):
                if progress_callback:
                    progress_callback(i, total_mock_files)
                time.sleep(0.02)
            if status_callback:
                status_callback("Extracted")
            return

        if status_callback:
            status_callback("Extracting")

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                members = zip_ref.infolist()          # ZipInfo objects carry external_attr
                total_files = len(members)
                target_folder.mkdir(parents=True, exist_ok=True)
                for i, info in enumerate(members):
                    if progress_callback and i % 50 == 0:
                        progress_callback(i, total_files)
                    # extract() sanitises the member name and returns the path it
                    # actually wrote; recomputing it from info.filename would let a
                    # crafted archive point the chmod below outside target_folder.
                    extracted = Path(zip_ref.extract(info, target_folder))
                    # Restore Unix permissions stored in the zip (upper 16 bits of
                    # external_attr), masked to rwx bits so archived setuid/setgid
                    # bits are never applied.
                    unix_mode = (info.external_attr >> 16) & 0o777
                    if unix_mode and extracted.exists():
                        extracted.chmod(unix_mode)
                if progress_callback:
                    progress_callback(total_files, total_files)
            if status_callback:
                status_callback("Extracted")

            # Zips built without Unix mode bits leave everything non-executable,
            # which would make post_install.sh below fail with EACCES.
            self._fix_isaacsim_permissions(target_folder)

            # Run post_install.sh if it exists
            post_install_script = target_folder / "post_install.sh"
            if post_install_script.exists():
                if status_callback:
                    status_callback("Post-Install")
                subprocess.run([str(post_install_script)], cwd=target_folder, check=True)
        except Exception:
            if target_folder.exists():
                shutil.rmtree(target_folder)
            raise
        finally:
            if zip_path.exists():
                zip_path.unlink()

    def _patch_pow_toml(
        self,
        pow_toml_path: Path,
        enable_ros: bool,
        isaacsim_ros_ws: str = "~/IsaacSim-ros_workspaces",
        sim_version: str | None = None,
    ) -> dict:
        """Update the settings init collected, leaving the rest of the file alone.

        tomlkit round-trips comments, key order and formatting, so only the three
        keys below are touched.  Keys the template has and this file lacks are
        deliberately **not** back-filled: PowConfig defaults every missing key,
        so an older pow.toml keeps working untouched.

        Returns:
            ``{key: (old, new)}`` for the keys whose value actually changed, with
            ``old`` set to ``None`` when the key was absent.  Empty when the file
            already says what init would write - nothing is written in that case,
            so a re-run of init is a true no-op.

        Raises:
            tomlkit.exceptions.ParseError: the file is not valid TOML.  Nothing
                is written, so the file survives intact.
        """
        doc = tomlkit.parse(pow_toml_path.read_text())

        patch = {
            "version": sim_version or PowConfig.ISAACSIM_VERSION,
            "enable_ros": enable_ros,
            "isaacsim_ros_ws": isaacsim_ros_ws,
        }

        # A document with no usable [sim] table gets one; anything else it holds
        # (such as [[profiles]]) is left where it is.
        sim = doc["sim"] if "sim" in doc and isinstance(doc["sim"], dict) else None

        changed = {}
        for key, value in patch.items():
            old = sim.get(key) if sim is not None else None
            if old is not None and old == value:
                continue
            changed[key] = (old, value)

        if not changed:
            return changed

        if sim is None:
            doc["sim"] = patch
        else:
            for key in changed:
                sim[key] = patch[key]

        pow_toml_path.write_text(tomlkit.dumps(doc))
        return changed

    def setup_omniverse_user_home_alias(self) -> dict:
        """Ensure ``user-home`` alias is set in the Omniverse config.

        Reads (or creates) ``~/.nvidia-omniverse/config/omniverse.toml`` and
        sets ``[aliases]."user-home"`` to the current user's home directory.

        Returns:
            dict with keys ``status`` ("created" | "updated" | "unchanged")
            and ``path`` (the config file path).
        """
        config_path = Path.home() / ".nvidia-omniverse" / "config" / "omniverse.toml"
        home_dir = str(Path.home())

        config_path.parent.mkdir(parents=True, exist_ok=True)

        if config_path.exists():
            doc = tomlkit.parse(config_path.read_text())
        else:
            doc = tomlkit.document()

        if "aliases" not in doc:
            doc.add("aliases", tomlkit.table())

        aliases = doc["aliases"]
        existing = aliases.get("user-home")

        if existing == home_dir:
            return {"status": "unchanged", "path": str(config_path)}

        status = "updated" if existing is not None else "created"
        aliases["user-home"] = home_dir
        config_path.write_text(tomlkit.dumps(doc))

        return {"status": status, "path": str(config_path)}
