"""AssetManager — manages local asset path setup for pow."""

from __future__ import annotations

import os
import importlib.resources
import tomlkit
from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from .models.pow_config import PowConfig
from .models.system_config import SystemConfig


# ── Data structures ───────────────────────────────────────────────────────────


@dataclass
class AssetListEntry:
    """A single registry asset enriched with live profile data (if available)."""

    group_name: str
    title: str
    name: str
    size: str             # human-readable e.g. '2.62 GB'
    status: str = "pending"
    completion_pct: float = 0.0
    url: str | list[str] = ""
    asset_type: str = ""


@dataclass
class AssetListData:
    """Result of get_asset_list_data(), consumed by the CLI."""

    local_path: str                              # empty = not configured
    symlink_ok: bool                             # symlink exists → real dir
    entries: List[AssetListEntry] = field(default_factory=list)


class AssetError(Exception):
    """Raised when an asset operation fails with a user-facing message."""


# ── Registry configuration ───────────────────────────────────────────────────

REGISTRIES = [
    {
        "file": "isaacsim_assets_5_1_0.toml",
        "root_key": "isaacsim_assets",
        "group_keys": ["isaacsim_5_1_0"],
    },
    {
        "file": "omniverse_assets.toml",
        "root_key": "omniverse",
        "group_keys": [
            "omni_3d_assets",
            "omni_sim_ready",
            "omni_materials",
            "omni_environments",
            "omni_workflows",
        ],
    },
]


class AssetManager:
    """Handles local asset path configuration, alias registration, and kit patching."""

    POW_ASSETS_ALIAS = "pow-assets"
    OMNIVERSE_TOML_PATH = Path.home() / ".nvidia-omniverse" / "config" / "omniverse.toml"

    # Sentinel comments used to detect an existing patch block in .kit files
    _KIT_PATCH_START = "# Local asset settings (added by pow cli)"
    _KIT_PATCH_END   = "# End: Local asset settings (added by pow cli)"

    # S3 URL keys for alias-support flags
    _ISAACSIM_S3_ALIAS_KEYS = (
        "http://omniverse-content-production.s3.us-west-2.amazonaws.com",
        "https://omniverse-content-production.s3.us-west-2.amazonaws.com",
        "http://omniverse-content-production.s3-us-west-2.amazonaws.com",
        "https://omniverse-content-production.s3-us-west-2.amazonaws.com",
    )
    _SIM_READY_S3_ALIAS_KEYS = (
        "http://omniverse-content-staging.s3.us-west-2.amazonaws.com",
        "https://omniverse-content-staging.s3.us-west-2.amazonaws.com",
    )

    def __init__(self):
        self._config = PowConfig()

    # ── Path accessors ────────────────────────────────────────────────────────

    @property
    def global_dir(self) -> Path:
        """The global pow directory (e.g. ~/.pow)."""
        return self._config.global_path

    def get_system_toml_path(self) -> Path:
        return self.global_dir / "system.toml"

    def get_assets_symlink_path(self) -> Path:
        return self.global_dir / "assets"

    def get_kit_path(self) -> Path:
        """Path to the .kit experience file of the project's Isaac Sim install."""
        try:
            version = self._config.get("version", PowConfig.ISAACSIM_VERSION)
        except RuntimeError:  # no pow.toml
            version = PowConfig.resolve_installed_version(self.global_dir)
        return (
            PowConfig.version_dir(version, self.global_dir)
            / "apps" / "isaacsim.exp.base.kit"
        )

    # ── Configuration queries ─────────────────────────────────────────────────

    def get_local_asset_path(self) -> str:
        """Get the currently configured local asset path from system.toml."""
        path = self.get_system_toml_path()
        if not path.exists():
            return ""
        return SystemConfig.from_file(path).asset.local_asset_path

    def is_asset_configured(self) -> bool:
        """Return True if [asset] is already set in system.toml."""
        return bool(self.get_local_asset_path())

    # ── Asset list data ───────────────────────────────────────────────────────

    def get_asset_list_data(self) -> AssetListData:
        """Return registry entries enriched with live profile data from all registries."""
        local_path = self.get_local_asset_path()
        symlink = self.get_assets_symlink_path()
        symlink_ok = symlink.is_symlink() and symlink.resolve().is_dir()

        profile = self._load_profile(symlink) if (local_path and symlink_ok) else None
        entries = self._load_registry_entries(profile)

        return AssetListData(
            local_path=local_path,
            symlink_ok=symlink_ok,
            entries=entries,
        )

    # ── set / unset ───────────────────────────────────────────────────────────

    def set_local_asset_path(self, asset_path: str) -> str:
        """Configure the local asset path.

        Steps:
        1. Reject if asset config in system.toml is already set.
        2. Reject if .pow/assets already exists and is a symlink.
        3. Validate the given path exists and is a directory.
        4. Resolve to an absolute path.
        5. Create the .pow/assets symlink.
        6. Write [asset] config in system.toml.
        7. Register pow-assets alias in omniverse.toml.

        Returns:
            The resolved absolute path that was set.

        Raises:
            AssetError: If any validation or operation step fails.
        """
        self._reject_if_already_configured()
        self._reject_if_symlink_exists()
        abs_path = self._validate_and_resolve(asset_path)

        self.global_dir.mkdir(parents=True, exist_ok=True)
        os.symlink(abs_path, self.get_assets_symlink_path())
        self._write_system_toml(abs_path)
        self._register_omniverse_alias(abs_path)

        profile_path = abs_path / "asset-profile.toml"
        if not profile_path.exists():
            profile_path.touch()

        return str(abs_path)

    def unset_local_asset_path(self) -> dict[str, str]:
        """Remove all asset configuration set by set_local_asset_path.

        Each step is performed independently; failures are collected and reported
        without aborting the remaining steps.

        Returns:
            A dict mapping step label → outcome message (for CLI feedback).

        Raises:
            AssetError: If none of the expected state was found (nothing to unset).
        """
        results: dict[str, str] = {}
        any_action = False

        steps = [
            ("Symlink",                    self._unset_symlink),
            ("system.toml [asset]",        self._unset_system_toml),
            ("omniverse.toml [aliases]",     self._unset_omniverse_aliases),
            ("isaacsim.exp.base.kit patch", self._unset_kit_patch),
        ]

        for label, step_fn in steps:
            try:
                outcome = step_fn()
                results[label] = outcome
                if "skipped" not in outcome.lower():
                    any_action = True
            except Exception as exc:
                results[label] = f"Failed: {exc}"

        if not any_action:
            raise AssetError(
                "No asset configuration was found. Nothing to unset.\n"
                "Run 'pow asset set <path>' to configure an asset path first."
            )

        return results

    # ── Asset installation ────────────────────────────────────────────────────

    def install_assets(self, target: str, is_group: bool, keep_path: str | None = None) -> None:
        import subprocess
        import shutil
        from ..common.utils import console

        system_config = (
            SystemConfig.from_file(self.get_system_toml_path())
            if self.get_system_toml_path().exists()
            else SystemConfig.default()
        )
        if not system_config.asset.use_local_asset:
            raise AssetError("Local asset usage is disabled or not configured in ~/.pow/system.toml (use_local_asset=false).\nRun 'pow asset set <path>' first to pick an installation directory.")
        
        target_path = self.get_assets_symlink_path()
        
        if not shutil.which("aria2c"):
            raise AssetError(
                "aria2c is not installed on your system.\n"
                "Please install it using:\n  [bold cyan]sudo apt update && sudo apt install aria2c[/bold cyan]"
            )
            
        data = self.get_asset_list_data()
        if is_group:
            to_install = [e for e in data.entries if e.group_name == target]
        else:
            to_install = [e for e in data.entries if e.name == target]
            
        if not to_install:
            raise AssetError(f"No assets found matching {'group' if is_group else 'name'} '{target}'")

        target_path.mkdir(parents=True, exist_ok=True)
        
        profile_path = target_path / "asset-profile.toml"
        if not profile_path.exists():
            profile_path.touch()
            
        try:
            profile_data = tomlkit.loads(profile_path.read_text())
        except Exception:
            profile_data = tomlkit.document()
            
        for entry in to_install:
            if profile_data.get(entry.name) is True:
                console.print(f"\n[bold green]✔[/bold green] {entry.title} ([dim]{entry.name}[/dim]) is already installed. Skipping.")
                continue

            console.print(f"\n[bold blue]⬇ Installing {entry.title} ([dim]{entry.name}[/dim])...[/bold blue]")
            
            urls = entry.url if isinstance(entry.url, list) else [entry.url]
            if not urls or not urls[0]:
                continue
                
            if entry.asset_type == "split_archive":
                base_name = urls[0].split("/")[-1]
                merged_filename = base_name.rsplit(".", 1)[0] if "." in base_name else base_name
            else:
                merged_filename = urls[0].split("/")[-1]
                
            skip_download = False
            if keep_path:
                keep_dir = Path(keep_path).resolve()
                keep_zip = keep_dir / merged_filename
                if keep_zip.exists():
                    console.print(f"   [dim]✔ Found existing cache in keep location: {merged_filename}[/dim]")
                    console.print("   [dim]Copying instead of downloading...[/dim]")
                    dest_zip = target_path / merged_filename
                    try:
                        subprocess.run(["cp", str(keep_zip), str(dest_zip)], check=True)
                        skip_download = True
                    except subprocess.CalledProcessError as e:
                        console.print(f"   [yellow]Failed to copy from keep location: {e}. Falling back to download...[/yellow]")
                        
            if skip_download:
                try:
                    self._unzip_with_progress(dest_zip, target_path)
                    console.print("   [dim]Cleaning up copied zip...[/dim]")
                    if dest_zip.exists():
                        dest_zip.unlink()
                except subprocess.CalledProcessError as e:
                    raise AssetError(f"Extraction failed for {dest_zip}. Error: {e}")
                    
                profile_data[entry.name] = True
                profile_path.write_text(tomlkit.dumps(profile_data))
                console.print(f"   [bold green]✔[/bold green] {entry.title} installed successfully!")
                continue

            downloaded_files = []
            
            for url in urls:
                if not url:
                    continue
                filename = url.split("/")[-1]
                file_path = target_path / filename
                aria2_file = target_path / f"{filename}.aria2"
                
                downloaded_files.append(file_path)
                
                if aria2_file.exists():
                    console.print(f"   [yellow]Incomplete download detected for {filename}. Resuming...[/yellow]")
                elif file_path.exists():
                    console.print(f"   [dim]✔ Found complete asset part: {filename}[/dim]")
                    continue
                else:
                    console.print(f"   [cyan]Downloading:[/cyan] {filename}")
                    
                try:
                    subprocess.run(
                        ["aria2c", url, "-d", str(target_path)],
                        check=True
                    )
                except subprocess.CalledProcessError as e:
                    raise AssetError(f"Download failed for {url}. Error: {e}")
            
            if entry.asset_type == "split_archive":
                self._extract_split_archive(entry, target_path, downloaded_files, keep_path)
            else:
                self._extract_standalone(entry, target_path, downloaded_files, keep_path)
            
            profile_data[entry.name] = True
            profile_path.write_text(tomlkit.dumps(profile_data))
            console.print(f"   [bold green]✔[/bold green] {entry.title} installed successfully!")

    def _unzip_with_progress(self, zip_path: Path, target_path: Path):
        import subprocess
        from ..common.utils import console
        from rich.progress import BarColumn, Progress, TextColumn
        
        info = subprocess.run(["unzip", "-qql", str(zip_path)], capture_output=True, text=True)
        total_files = len(info.stdout.splitlines()) if info.stdout else 0
        
        with Progress(
            TextColumn("   [dim]Extracting archive...[/dim]"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("Extracting", total=total_files)
            process = subprocess.Popen(
                ["unzip", "-o", str(zip_path), "-d", str(target_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True
            )
            if process.stdout:
                for line in process.stdout:
                    if line.strip().startswith(("inflating:", "creating:", "extracting:", "linking:")):
                        progress.advance(task)
            process.wait()
            if process.returncode != 0:
                raise subprocess.CalledProcessError(process.returncode, process.args)
            progress.update(task, completed=total_files)

    def _extract_standalone(self, entry: AssetListEntry, target_path: Path, files: list[Path], keep_path: str | None = None):
        import subprocess
        from ..common.utils import console
        if not files: return
        file_path = files[0]
        
        try:
            self._unzip_with_progress(file_path, target_path)
            
            if keep_path:
                keep_dir = Path(keep_path).resolve()
                keep_dir.mkdir(parents=True, exist_ok=True)
                console.print(f"   [dim]Moving zip files to {keep_dir}...[/dim]")
                if file_path.exists():
                    subprocess.run(["mv", str(file_path), str(keep_dir)], check=True)
            else:
                console.print("   [dim]Cleaning up zip files...[/dim]")
                if file_path.exists():
                    file_path.unlink()
        except subprocess.CalledProcessError as e:
            raise AssetError(f"Extraction failed for {file_path}. Error: {e}")
            
    def _extract_split_archive(self, entry: AssetListEntry, target_path: Path, files: list[Path], keep_path: str | None = None):
        import subprocess
        from ..common.utils import console
        if not files: return
        
        base_name = files[0].name
        merged_filename = base_name.rsplit(".", 1)[0] if "." in base_name else base_name
        merged_zip = target_path / merged_filename
        
        if merged_zip.exists():
            merged_zip.unlink()
            
        from rich.progress import BarColumn, Progress, TextColumn
        
        total_size = sum(p.stat().st_size for p in files if p.exists())
        
        with Progress(
            TextColumn("   [dim]Merging zip parts...[/dim]"),
            BarColumn(bar_width=40),
            TextColumn("[progress.percentage]{task.percentage:>3.1f}%"),
            console=console,
        ) as progress:
            task = progress.add_task("Progress:", total=total_size)
            with open(merged_zip, "wb") as outfile:
                for part in files:
                    if not part.exists():
                        raise AssetError(f"Missing downloaded part: {part}")
                    with open(part, "rb") as infile:
                        while chunk := infile.read(1024 * 1024 * 10):
                            outfile.write(chunk)
                            progress.update(task, advance=len(chunk))
        
        try:
            self._unzip_with_progress(merged_zip, target_path)
            
            if keep_path:
                keep_dir = Path(keep_path).resolve()
                keep_dir.mkdir(parents=True, exist_ok=True)
                if merged_zip.exists():
                    console.print(f"   [dim]Moving merged zip to {keep_dir}...[/dim]")
                    subprocess.run(["mv", str(merged_zip), str(keep_dir)], check=True)
                    console.print("   [dim]Cleaning up zip parts...[/dim]")
                    for part in files:
                        if part.exists():
                            part.unlink()
                else:
                    console.print(f"   [dim]Moving zip parts to {keep_dir}...[/dim]")
                    for part in files:
                        if part.exists():
                            subprocess.run(["mv", str(part), str(keep_dir)], check=True)
            else:
                console.print("   [dim]Cleaning up zip files...[/dim]")
                for part in files:
                    if part.exists(): part.unlink()
                if merged_zip.exists(): merged_zip.unlink()
        except subprocess.CalledProcessError as e:
            raise AssetError(f"Extraction failed for {merged_zip}. Error: {e}")

    # ── Kit patching ──────────────────────────────────────────────────────────

    def patch_isaacsim_kit(self) -> bool:
        """Append local asset settings block to isaacsim.exp.base.kit.

        Returns:
            True if the file was patched, False if it was already patched.

        Raises:
            AssetError: If the .kit file does not exist.
        """
        kit_path = self.get_kit_path()
        if not kit_path.exists():
            raise AssetError(
                f"Kit file not found: '{kit_path}'\n"
                "Make sure Isaac Sim is installed under the pow global directory."
            )

        existing = kit_path.read_text(encoding="utf-8")
        if self._KIT_PATCH_START in existing:
            return False

        patch_block = self._build_kit_patch_block()
        with kit_path.open("a", encoding="utf-8") as fh:
            fh.write(patch_block)

        return True

    def unpatch_isaacsim_kit(self) -> bool:
        """Remove the pow-added settings block from isaacsim.exp.base.kit.

        Returns:
            True if the block was found and removed, False if it was not present.
        """
        kit_path = self.get_kit_path()
        if not kit_path.exists():
            return False

        text = kit_path.read_text(encoding="utf-8")
        if self._KIT_PATCH_START not in text:
            return False

        start_idx = text.find(self._KIT_PATCH_START)
        end_idx = text.find(self._KIT_PATCH_END, start_idx)
        if end_idx == -1:
            return False  # Malformed patch — leave the file untouched

        end_idx += len(self._KIT_PATCH_END)

        # Consume any trailing newline after the end sentinel
        if end_idx < len(text) and text[end_idx] == "\n":
            end_idx += 1

        # Strip any extra blank lines immediately before the patch block
        pre = text[:start_idx]
        if pre.endswith("\n"):
            pre = pre.rstrip("\n") + "\n"

        kit_path.write_text(pre + text[end_idx:], encoding="utf-8")
        return True

    # ── S3 alias registration ─────────────────────────────────────────────────

    def register_isaacsim_s3_aliases(self) -> None:
        """Add Isaac Sim production S3 URL → assets symlink mappings to omniverse.toml."""
        self._write_s3_aliases(self._ISAACSIM_S3_ALIAS_KEYS)

    def register_sim_ready_s3_aliases(self) -> None:
        """Add Omniverse staging S3 URL → assets symlink mappings to omniverse.toml."""
        self._write_s3_aliases(self._SIM_READY_S3_ALIAS_KEYS)

    # ── Private: validation helpers ───────────────────────────────────────────

    def _reject_if_already_configured(self) -> None:
        if self.is_asset_configured():
            existing = self.get_local_asset_path()
            raise AssetError(
                f"Asset path is already configured: '{existing}'\n"
                "Run 'pow asset unset' to remove the current configuration first."
            )

    def _reject_if_symlink_exists(self) -> None:
        assets_symlink = self.get_assets_symlink_path()
        if assets_symlink.is_symlink():
            raise AssetError(
                f"'{assets_symlink}' is already a symlink.\n"
                "Run 'pow asset unset' to remove the current asset configuration "
                "before running this command again."
            )

    @staticmethod
    def _validate_and_resolve(asset_path: str) -> Path:
        given = Path(asset_path)
        if not given.exists():
            raise AssetError(f"Path does not exist: '{asset_path}'")
        if not given.is_dir():
            raise AssetError(f"Path is not a directory: '{asset_path}'")
        return given.resolve()

    # ── Private: system.toml I/O ──────────────────────────────────────────────

    def _write_system_toml(self, abs_path: Path) -> None:
        toml_path = self.get_system_toml_path()
        toml_path.parent.mkdir(parents=True, exist_ok=True)

        system_config = (
            SystemConfig.from_file(toml_path)
            if toml_path.exists()
            else SystemConfig.default()
        )

        system_config.asset.local_asset_path = str(abs_path)
        system_config.asset.use_local_asset = True

        self._save_system_config(toml_path, system_config)

    def _clear_system_toml_asset(self) -> bool:
        """Reset [asset] in system.toml to defaults. Returns True if it was set."""
        toml_path = self.get_system_toml_path()
        if not toml_path.exists():
            return False

        system_config = SystemConfig.from_file(toml_path)
        was_set = bool(system_config.asset.local_asset_path)

        system_config.asset.local_asset_path = ""
        system_config.asset.use_local_asset = False

        self._save_system_config(toml_path, system_config)
        return was_set

    @staticmethod
    def _save_system_config(toml_path: Path, system_config: SystemConfig) -> None:
        doc = tomlkit.document()
        for section, values in system_config.to_dict().items():
            table = tomlkit.table()
            for k, v in values.items():
                table.add(k, v)
            doc.add(section, table)
        toml_path.write_text(tomlkit.dumps(doc))

    # ── Private: omniverse.toml I/O ───────────────────────────────────────────

    def _read_omniverse_doc(self) -> tomlkit.TOMLDocument:
        """Load or create the omniverse.toml document."""
        if self.OMNIVERSE_TOML_PATH.exists():
            return tomlkit.parse(self.OMNIVERSE_TOML_PATH.read_text())
        return tomlkit.document()

    def _save_omniverse_doc(self, doc: tomlkit.TOMLDocument) -> None:
        self.OMNIVERSE_TOML_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.OMNIVERSE_TOML_PATH.write_text(tomlkit.dumps(doc))

    def _register_omniverse_alias(self, abs_path: Path) -> None:
        """Add or update 'pow-assets' entry in [aliases] of omniverse.toml."""
        doc = self._read_omniverse_doc()
        if "aliases" not in doc:
            doc.add("aliases", tomlkit.table())
        doc["aliases"][self.POW_ASSETS_ALIAS] = str(self.get_assets_symlink_path())
        self._save_omniverse_doc(doc)

    def _clear_omniverse_aliases(self) -> bool:
        """Remove pow-added aliases from omniverse.toml. Returns True if any were removed."""
        if not self.OMNIVERSE_TOML_PATH.exists():
            return False
        doc = self._read_omniverse_doc()
        if "aliases" not in doc:
            return False

        aliases_to_remove = [self.POW_ASSETS_ALIAS]
        aliases_to_remove.extend(self._ISAACSIM_S3_ALIAS_KEYS)
        aliases_to_remove.extend(self._SIM_READY_S3_ALIAS_KEYS)

        removed_any = False
        for alias in aliases_to_remove:
            if alias in doc["aliases"]:
                del doc["aliases"][alias]
                removed_any = True

        if removed_any:
            self._save_omniverse_doc(doc)
            
        return removed_any

    def _write_s3_aliases(self, keys: tuple[str, ...]) -> None:
        """Write the given S3 URL keys → assets symlink into omniverse.toml [aliases]."""
        doc = self._read_omniverse_doc()
        if "aliases" not in doc:
            doc.add("aliases", tomlkit.table())
        symlink_path = str(self.get_assets_symlink_path())
        for url in keys:
            doc["aliases"][url] = symlink_path
        self._save_omniverse_doc(doc)

    # ── Private: unset step functions ─────────────────────────────────────────

    def _unset_symlink(self) -> str:
        symlink = self.get_assets_symlink_path()
        if symlink.is_symlink():
            symlink.unlink()
            return f"Removed {symlink}"
        return "Not found — skipped"

    def _unset_system_toml(self) -> str:
        return "Cleared" if self._clear_system_toml_asset() else "Not configured — skipped"

    def _unset_omniverse_aliases(self) -> str:
        return "Removed" if self._clear_omniverse_aliases() else "Not found — skipped"

    def _unset_kit_patch(self) -> str:
        return "Removed" if self.unpatch_isaacsim_kit() else "Patch block not found — skipped"

    # ── Private: asset data loading ───────────────────────────────────────────

    @staticmethod
    def _load_profile(symlink: Path) -> dict | None:
        """Load asset-profile.toml from the symlink target, if it exists."""
        profile_path = symlink.resolve() / "asset-profile.toml"
        if not profile_path.exists():
            return None
        try:
            return tomlkit.loads(profile_path.read_text())
        except Exception:
            return None

    @staticmethod
    def _load_registry_entries(profile: dict | None) -> list[AssetListEntry]:
        """Parse all configured registry files and merge with profile data."""
        try:
            import tomllib
        except ImportError:
            import tomli as tomllib  # type: ignore[no-redef]

        entries: list[AssetListEntry] = []

        for reg_config in REGISTRIES:
            try:
                registry_bytes = (
                    importlib.resources.files("pow_cli")
                    .joinpath("data")
                    .joinpath("asset-registry")
                    .joinpath(reg_config["file"])
                    .read_bytes()
                )
                registry = tomllib.loads(registry_bytes.decode())
                root = registry.get(reg_config["root_key"], {})

                for group_key in reg_config["group_keys"]:
                    for raw in root.get(group_key, []):
                        name = raw.get("name", "")
                        status = "not-downloaded"
                        completion_pct = 0.0

                        if profile:
                            if profile.get(name) is True:
                                status = "downloaded"
                                completion_pct = 100.0

                        entries.append(
                            AssetListEntry(
                                group_name=group_key,
                                title=raw.get("title", name),
                                name=name,
                                size=raw.get("size", "—"),
                                status=status,
                                completion_pct=completion_pct,
                                url=raw.get("url", ""),
                                asset_type=raw.get("type", "standalone"),
                            )
                        )
            except Exception:
                continue

        return entries

    # ── Private: kit patch block builder ──────────────────────────────────────

    def _build_kit_patch_block(self) -> str:
        """Build the reduced kit patch text block."""
        return (
            "\n"
            f"{self._KIT_PATCH_START}\n"
            "[settings]\n"
            f'exts."isaacsim.asset.browser".visible_after_startup = true\n'
            f"{self._KIT_PATCH_END}\n"
        )
