"""Init command implementation."""

import json
import time
from pathlib import Path

import click
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm

from ..common.installation import download_with_progress
from ..common.prompt import ask_choice, ask_path
from ..common.utils import console
from ..core.initializer import Initializer
from ..core.models.pow_config import PowConfig
from ..core.ros_manager import RosManager



# ── Logo ──────────────────────────────────────────────────────────────────────
def draw_logo():
# A brighter, punchier neon green
    NEON_GREEN = "#76ff7a" 
    
    # Refined font with better curves and proportions
    font = {
        'P': ["█████▄", "██▄▄██", "██▀▀▀ ", "██    "],
        'O': ["▄████▄", "██  ██", "██  ██", "▀████▀"],
        'W': ["██    ██", "██ ▄▄ ██", "████████", "▀██  ██▀"],
        'E': ["██████", "██▄▄▄ ", "██▀▀▀ ", "██████"],
        'R': ["█████▄", "██▄▄██", "██▀██ ", "██  ██"],
        'A': ["▄████▄", "██▄▄██", "██▀▀██", "██  ██"],
        'C': ["▄█████", "██    ", "██    ", "▀█████"],
        'K': ["██  ██", "██▄██ ", "██▀██ ", "██  ██"],
    }

    text = "POWERPACK"
    
    console.print("\n")
    
    # 1. Top UI framing line
    console.print("[dim white]" + "─" * 66 + "[/]\n")

    # 2. Perfectly Centered ISAAC Badge
    # (64 total width of text - 13 width of badge) / 2 = 25 spaces of padding
    console.print("                         [bold black on white]  I S A A C  [/]\n")

    # 3. The POWERPACK Text
    for i in range(4):
        line_content = ""
        for char in text:
            if char in font:
                # Add 1 space between each letter for breathability
                line_content += font[char][i] + " " 
        
        console.print(f"[{NEON_GREEN}]{line_content}[/]")

    # 4. Bottom UI framing and prompt
    console.print("\n[dim white]" + "─" * 66 + "[/]")

# ── Step helpers ──────────────────────────────────────────────────────────────

def _step1_check_config(global_dir_name: str) -> bool:
    """Print config header and verify pyproject.toml exists. Return False to abort."""
    if not Path("pyproject.toml").exists():
        console.print(
            "\n[bold red][1/10] ❌ Error:[/bold red] pyproject.toml not found. "
            "Please run this command in a valid project directory."
        )
        return False
    console.print(
        f"\n[bold blue][1/10] 🔧 Config:[/bold blue] "
        f"Using global directory [bold green]'{global_dir_name}'[/bold green]"
    )
    return True


def _step2_check_existing_config(initializer: Initializer) -> bool:
    """Ask whether to override an existing pow.toml. Returns override flag."""
    if not Path("pow.toml").exists():
        console.print(
            "[bold blue][2/10] 🔍 Check Existing Config [/bold blue] "
            "No existing pow.toml found. Proceeding..."
        )
        return True  # nothing to preserve, will create fresh

    console.print(
        "[bold blue][2/10] 🔍 Check Existing Config: [/bold blue] "
        "[yellow]Found existing pow.toml[/yellow]"
    )
    override = Confirm.ask(
        "   Update settings in existing pow.toml?",
        default=False,
    )
    if override:
        console.print(
            "   [green]Will update only version, enable_ros and isaacsim_ros_ws.[/green]"
        )
        console.print("   [dim]Your other settings and comments are kept.[/dim]")
    else:
        console.print("   [yellow]Proceeding with existing pow.toml.[/yellow]")
        initializer.read_config()
        console.print("   [green]✔ Read existing pow.toml configuration.[/green]")
    return override


def _step3_global_folder(initializer: Initializer, global_path):
    """Create the .pow global folder and print the result."""
    console.print(
        f"[bold blue][3/10] 📂 Global Folder:[/bold blue] Preparing [dim]{global_path}[/dim]..."
    )
    init_data = initializer.create_global_folder()

    if init_data["global_existed"]:
        console.print(
            f"   [yellow]✔[/yellow] Global directory [dim]{global_path}[/dim] already exists."
        )
    else:
        console.print(
            f"   [green]✔[/green] Global directory [dim]{global_path}[/dim] prepared successfully."
        )

    system_toml_result = initializer.create_system_toml()
    if system_toml_result["status"] == "Created":
        console.print(
            f"   [green]✔[/green] Created system.toml: [dim]{system_toml_result['path']}[/dim]"
        )
    else:
        console.print(
            f"   [yellow]✔[/yellow] system.toml already exists: [dim]{system_toml_result['path']}[/dim]"
        )


def _version_choices() -> list[tuple[str, str]]:
    """Versions installable on this host's architecture, latest first, annotated for the picker."""
    installed = set(PowConfig.installed_versions())
    versions = PowConfig.versions_for_arch()
    latest = versions[0] if versions else None

    choices = []
    for version in versions:
        notes = []
        if version == latest:
            notes.append("latest")
        if version in installed:
            notes.append("installed")
        choices.append((version, ", ".join(notes)))
    return choices


def _resolve_sim_version(flag_version: str | None, config_version: str | None) -> str:
    """Decide which Isaac Sim version to install.

    Precedence: ``--sim-version`` flag, then ``[sim] version`` from an existing
    pow.toml the user chose to keep, then an interactive prompt.
    """
    if flag_version:
        console.print(
            f"   Using version from --sim-version: [bold green]{flag_version}[/bold green]"
        )
        return flag_version

    if config_version:
        if config_version not in PowConfig.SUPPORTED_ISAACSIM_VERSIONS:
            raise click.ClickException(
                f"Unsupported Isaac Sim version '{config_version}' in pow.toml. "
                f"Supported versions: {', '.join(PowConfig.SUPPORTED_ISAACSIM_VERSIONS)}."
            )
        console.print(
            f"   Using version from pow.toml: [bold green]{config_version}[/bold green]"
        )
        return config_version

    available = PowConfig.versions_for_arch()
    default = PowConfig.configured_default_version() or (
        available[0] if available else PowConfig.ISAACSIM_VERSION
    )
    PowConfig.release(default)
    return ask_choice(
        "Select Isaac Sim version",
        _version_choices(),
        default=default,
    )


def _step4_download_isaacsim(
    initializer: Initializer,
    flag_version: str | None = None,
    config_version: str | None = None,
) -> dict | None:
    """Select and install Isaac Sim. Return None on installation failure."""
    console.print("[bold blue][4/10] 📦 Isaac Sim App:[/bold blue] Select a version to install")
    version = _resolve_sim_version(flag_version, config_version)
    try:
        return download_with_progress(initializer, version)
    except Exception as error:
        console.print(f"   [bold red]❌ Error:[/bold red] {error}")
        return None


def _step5_optimization(initializer: Initializer, isaacsim_path: str):
    """Apply Isaac Sim post-install fixes."""
    console.print("[bold blue][5/10] ⚡ Optimization:[/bold blue] Applying Isaac Sim fixes...")
    with console.status("Fixing isaacsim.asset.browser cache file missing..."):
        fixed = initializer.fix_asset_browser_cache(isaacsim_path)
    if fixed:
        console.print("   [green]✔[/green] Created missing cache file.")
    else:
        console.print("   [yellow]✔[/yellow] Cache file already exists.")


def _step6_ros_integration(
    initializer: Initializer,
    global_dir_name: str,
    forced_value: bool | None = None,
    forced_ws: str | None = None,
    sim_version: str | None = None,
) -> tuple[bool, str]:
    """Prompt for ROS integration and set it up.

    Returns:
        (ros_enabled, isaacsim_ros_ws)  –  whether ROS was enabled and the
        tilde-relative path chosen for IsaacSim-ros_workspaces.
    """
    default_ws = "~/IsaacSim-ros_workspaces"
    ros_mgr = RosManager(config=initializer.config)
    console.print("[bold blue][6/10] 🤖 ROS Integration:[/bold blue]")
    
    if forced_value is not None:
        enabled = forced_value
        status_text = "[bold green]enabled[/bold green]" if enabled else "[bold yellow]disabled[/bold yellow]"
        console.print(f"   Using existing ROS setting from pow.toml: {status_text}")
    else:
        enabled = Confirm.ask("   Enable ROS integration?", default=True)

    if not enabled:
        console.print("   [yellow]⊖[/yellow] Skipping ROS integration.")
        return False, default_ws

    # Use existing workspace path from config, or ask the user
    if forced_ws is not None:
        ws_path = forced_ws
        console.print(f"   Using existing workspace path from pow.toml: [bold green]{ws_path}[/bold green]")
    else:
        ws_path = ask_path(
            "   Path to clone IsaacSim-ros_workspaces",
            default=default_ws,
        )
    # Normalise: keep tilde-relative for storage, but resolve for display
    if ws_path.startswith("~"):
        display_path = ws_path
    else:
        # Convert absolute paths back to tilde form when possible
        home = str(Path.home())
        if ws_path.startswith(home):
            display_path = "~" + ws_path[len(home):]
        else:
            display_path = ws_path
    console.print(f"   [dim]Workspace path:[/dim] {display_path}")

    ros_cloned = False

    def ros_status_callback(state):
        nonlocal ros_cloned
        if state == "cloning":
            ros_cloned = True
            status.update("[bold green]Cloning Isaac Sim ROS workspace...")
        elif state == "existed":
            status.update("[bold yellow]Isaac Sim ROS workspace already exists.")

    # Resolve the tilde path for actual filesystem operations
    resolved_ws = Path(ws_path).expanduser()

    ros_setup_failed = False

    with console.status("Preparing ROS workspace...") as status:
        try:
            ros_res = ros_mgr.setup_ros_workspace(
                status_callback=ros_status_callback,
                ws_path=resolved_ws,
                sim_version=sim_version,
            )
        except Exception as e:
            ros_setup_failed = True
            console.print(f"   [bold red]❌ ROS Setup Error:[/bold red] {e}")

    if ros_setup_failed:
        console.print("   [yellow]⊖[/yellow] Skipping remaining steps due to ROS setup error.")
        raise SystemExit(1)

    if ros_cloned:
        console.print(
            f"   [green]✔[/green] Cloned IsaacSim-ros_workspaces "
            f"([bold]{ros_res['ws_ref']}[/bold]) to [dim]{display_path}[/dim]"
        )
    else:
        console.print(f"   [yellow]✔[/yellow] IsaacSim-ros_workspaces already available in [dim]{display_path}[/dim]")

    bridge_distro = ros_mgr.config.ros_bridge
    console.print(
        f"   [green]✔[/green] ROS bridge: [bold]{bridge_distro}[/bold] "
        f"(ros_bridge in pow.toml, host Ubuntu {ros_res['ubuntu_version']}) "
        f"via Isaac Sim internal libs."
    )

    if not RosManager.docker_image_supported():
        console.print(
            f"   [yellow]⊖[/yellow] Skipping ROS Docker image build: "
            f"{RosManager.docker_image_unsupported_message()}"
        )
        return True, display_path

    # Build pow_simros Docker image
    simros_already_built = False

    def simros_status_callback(state):
        nonlocal simros_already_built
        if state == "simros_built":
            simros_already_built = True
            simros_status.update("[bold yellow]pow_simros image already exists.")
        elif state == "simros_building":
            simros_status.update("[bold green]Building pow_simros image...")
        elif state.startswith("simros_building:"):
            line = state[len("simros_building:"):]
            simros_status.update(f"[bold green]pow_simros build:[/bold green] [dim]{line[:80]}[/dim]")

    def confirm_simros_rebuild(image, version):
        simros_status.stop()
        try:
            console.print(
                f"   ROS image '{image}' is unlabelled or targets another simulator. "
                "Rebuilding updates its tag using Docker's cache. Existing containers "
                "and workspace files are preserved; recreate containers explicitly "
                "to use the rebuilt image."
            )
            return Confirm.ask(f"   Rebuild '{image}' for Isaac Sim {version}?", default=False)
        finally:
            simros_status.start()

    with console.status("Building pow_simros image...") as simros_status:
        try:
            ros_mgr.build_simros_image(
                status_callback=simros_status_callback,
                ws_path=resolved_ws,
                sim_version=sim_version,
                confirm_rebuild=confirm_simros_rebuild,
            )
        except Exception as e:
            console.print(f"   [bold red]❌ pow_simros Build Error:[/bold red] {e}")
            console.print("   [yellow]⊖[/yellow] Skipping remaining steps due to build error.")
            raise SystemExit(1)

    simros_label = f"pow_simros_[bold]{ros_res['ros_distro']}[/bold]"
    if simros_already_built:
        console.print(f"   [yellow]✔[/yellow] Docker image {simros_label} already exists.")
    else:
        console.print(f"   [green]✔[/green] Docker image {simros_label} built successfully.")

    # Build custom ROS image layered on top of pow_simros_<distro>
    custom_dockerfile = ros_mgr.config.ros_dockerfile
    if custom_dockerfile:
        custom_image = ros_mgr.config.ros_docker_image

        def custom_status_callback(state):
            if state == "custom_building":
                custom_status.update(f"[bold green]Building custom image '{custom_image}'...")
            elif state.startswith("custom_building:"):
                line = state[len("custom_building:"):]
                custom_status.update(f"[bold green]custom build:[/bold green] [dim]{line[:80]}[/dim]")

        with console.status(f"Building custom image '{custom_image}'...") as custom_status:
            try:
                ros_mgr.build_custom_ros_image(
                    status_callback=custom_status_callback,
                    sim_version=sim_version, ws_path=resolved_ws,
                )
            except Exception as e:
                console.print(f"   [bold red]❌ Custom ROS Build Error:[/bold red] {e}")
                console.print("   [yellow]⊖[/yellow] Skipping remaining steps due to build error.")
                raise SystemExit(1)

        console.print(
            f"   [green]✔[/green] Custom Docker image [bold]{custom_image}[/bold] "
            f"built from [dim]{custom_dockerfile}[/dim]."
        )

    return True, display_path


def _step7_project_structure(initializer: Initializer):
    """Create local project folders and .gitignore."""
    console.print("[bold blue][7/10] 🏗️ Project Structure:[/bold blue] Creating local folders...")
    local_folders = ["exts", ".modules", "usda"]

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=True,
    ) as progress:
        task = progress.add_task(
            description="Setting up project folders...", total=len(local_folders) + 1
        )
        struct_data = initializer.setup_project_structure(local_folders)
        for res in struct_data["results"]:
            progress.update(task, advance=1, description=f"Setting up {res['path']}...")
            time.sleep(0.1)

    console.print("   [green]✔[/green] Local folders created.")

    gitignore_res = next((r for r in struct_data["results"] if r["path"] == ".gitignore"), None)
    if gitignore_res and gitignore_res["status"] == "Created from template":
        console.print("   [green]✔[/green] Created .gitignore (from template)")
    elif gitignore_res and gitignore_res["status"] == "Template not found":
        console.print("   [yellow]⚠[/yellow] .gitignore template not found. [dim]Skipped.[/dim]")
    else:
        console.print("   [yellow]✔[/yellow] .gitignore already exists. [dim]Kept existing.[/dim]")


def _step8_project_link(initializer: Initializer, sim_version: str | None = None) -> dict | None:
    """Symlink managed Isaac Sim to local project.

    Returns the link result, or None when it could not be linked - everything
    after this step describes the linked install, so the caller must stop.
    """
    console.print("[bold blue][8/10] 🔗 Project Link:[/bold blue] Linking Isaac Sim to project...")
    result = initializer.link_managed_isaacsim(version=sim_version)
    if result["status"] == "Created":
        console.print(f"   [green]✔[/green] Created symlink: [dim]{result['path']}[/dim]")
    elif result["status"] == "Repointed":
        console.print(
            f"   [green]✔[/green] Re-pointed symlink [dim]{result['path']}[/dim] "
            f"to Isaac Sim {sim_version} [dim](was {result['previous']})[/dim]"
        )
    elif result["status"] == "Existed":
        console.print(f"   [yellow]✔[/yellow] Symlink already exists: [dim]{result['path']}[/dim]")
    elif result["status"] == "Error":
        console.print(f"   [bold red]❌ Error:[/bold red] {result['message']}")
        return None
    return result


#: VSCode config outcomes that are not a problem, mapped to how they are marked.
_VSCODE_OK_STATUSES = {
    "Copied": "green",
    "Copied and patched": "green",
    "Created": "green",
    "Updated": "green",
    "Already up to date": "yellow",
}


def _step9_vscode_setup(
    initializer: Initializer,
    version: str | None = None,
    version_changed: bool = True,
):
    """Setup VSCode configuration for the project.

    *version_changed* comes from step 8: the Isaac Sim extension paths are
    rewritten only when the project moved to a different version.
    """
    console.print("[bold blue][9/10] 💻 VSCode Config:[/bold blue] Setting up VSCode configs...")
    result = initializer.setup_vscode_configs(version=version, version_changed=version_changed)

    if result["status"] != "Success":
        console.print(f"   [bold red]❌ Error:[/bold red] {result['message']}")
        return

    for res in result["results"]:
        status = res["status"]
        colour = _VSCODE_OK_STATUSES.get(status)
        if status == "Error":
            console.print(f"   [bold red]❌[/bold red] {res['file']}: [dim]{res.get('message', '')}[/dim]")
            console.print("      Fix it, or delete it and re-run [bold]pow init[/bold].")
            continue

        symbol = f"[{colour}]✔[/{colour}]" if colour else "[yellow]⚠[/yellow]"
        note = " [dim](kept your other settings)[/dim]" if status == "Updated" else ""
        console.print(f"   {symbol} {res['file']}: [dim]{status}[/dim]{note}")

        for key, (old, new) in (res.get("changed") or {}).items():
            old_text = "[dim]unset[/dim]" if old is None else _json_value(old)
            new_text = "[dim]removed[/dim]" if new is None else f"[bold]{_json_value(new)}[/bold]"
            console.print(f"       [dim]{key}:[/dim] {old_text} → {new_text}", highlight=False)

        if res["file"] == "settings.json" and not version_changed:
            console.print(
                f"       [dim]python.analysis.extraPaths: kept "
                f"(Isaac Sim {result['version']} unchanged)[/dim]"
            )

        if res.get("warning"):
            console.print(f"      [yellow]⚠[/yellow] [dim]{res['warning']}[/dim]")


def _json_value(value) -> str:
    """Render a settings value the way settings.json spells it, shortening containers."""
    if isinstance(value, (list, dict)) and len(value) > 3:
        return f"[dim]{len(value)} entries[/dim]"
    return json.dumps(value)


def _toml_value(value) -> str:
    """Render a setting the way pow.toml spells it, so diffs read like the file."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _step10_finalize(
    initializer: Initializer,
    override_pow_toml: bool,
    ros_enabled: bool,
    isaacsim_ros_ws: str = "~/IsaacSim-ros_workspaces",
    sim_version: str | None = None,
) -> bool:
    """Generate pow.toml configuration. Returns False when it could not be written."""
    # Both calls return their outcome instead of printing, so the step header can
    # be rendered afterwards and carry the right icon.
    alias_result = initializer.setup_omniverse_user_home_alias()
    result = initializer.create_pow_toml(
        override=override_pow_toml,
        enable_ros=ros_enabled,
        isaacsim_ros_ws=isaacsim_ros_ws,
        sim_version=sim_version,
    )
    failed = result["status"] == "Error"

    icon = "❌" if failed else "✅"
    console.print(
        f"[bold blue][10/10] {icon} Finalizing:[/bold blue] Generating configuration..."
    )

    if alias_result["status"] == "created":
        console.print(f"   [green]✔[/green] Added user-home alias in [dim]{alias_result['path']}[/dim]")
    elif alias_result["status"] == "updated":
        console.print(f"   [green]✔[/green] Updated user-home alias in [dim]{alias_result['path']}[/dim]")
    else:
        console.print(f"   [yellow]✔[/yellow] user-home alias already set in [dim]{alias_result['path']}[/dim]")

    if result["status"] == "Created":
        console.print("   [green]✔[/green] Created pow.toml (from template)")
    elif result["status"] == "Updated":
        changed = result.get("changed") or {}
        if not changed:
            console.print("   [yellow]✔[/yellow] pow.toml already up to date")
        else:
            console.print(
                "   [green]✔[/green] Updated pow.toml "
                "[dim](kept your other settings)[/dim]"
            )
            for key, (old, new) in changed.items():
                old_text = "[dim]unset[/dim]" if old is None else _toml_value(old)
                console.print(
                    f"       [dim]{key}:[/dim] {old_text} → [bold]{_toml_value(new)}[/bold]",
                    highlight=False,
                )
    elif result["status"] == "Existed":
        console.print("   [yellow]✔[/yellow] Kept existing pow.toml")
    elif failed:
        console.print("   [bold red]❌ Error:[/bold red] pow.toml could not be parsed")
        console.print(f"      [dim]{result['message']}[/dim]")
        console.print("      Fix it, or delete it and re-run [bold]pow init[/bold].")
    else:
        console.print("   [yellow]⚠[/yellow] pow.toml template not found. [dim]Skipped.[/dim]")

    return not failed


# ── Command entry point ───────────────────────────────────────────────────────

@click.command(name="init")
@click.option(
    "--sim-version",
    "sim_version",
    type=click.Choice(PowConfig.SUPPORTED_ISAACSIM_VERSIONS),
    default=None,
    help="Isaac Sim version to install. Skips the interactive prompt.",
)
def init_cmd(sim_version: str | None):
    """Initialize Isaac Sim project.

    \b
    The Isaac Sim version comes from --sim-version, then from `[sim] version`
    in an existing pow.toml you choose to keep, then from an interactive prompt
    (global default or latest).
    """
    initializer = Initializer()
    config = initializer.get_config_path()
    global_dir_name = config["global_dir_name"]
    global_path = config["global_path"]

    # draw_logo()

    console.print(
            "\n"
            "[bold cyan]🚀 Initialization Pow Project[/bold cyan]",
    )

    if not _step1_check_config(global_dir_name):
        return

    override_pow_toml = _step2_check_existing_config(initializer)
    _step3_global_folder(initializer, global_path)

    # Reuse settings from an existing pow.toml the user chose to keep.
    ros_forced = None
    ros_ws_forced = None
    version_forced = None
    if Path("pow.toml").exists():
        try:
            if not override_pow_toml or sim_version is not None:
                ros_forced = initializer.config.get("enable_ros", False)
                ros_ws_forced = initializer.config.get("isaacsim_ros_ws", None)
            if not override_pow_toml:
                version_forced = initializer.config.get("version", None)
        except Exception:
            pass

    download_result = _step4_download_isaacsim(
        initializer, flag_version=sim_version, config_version=version_forced,
    )
    if download_result is None:
        return

    resolved_version = download_result["version"]

    _step5_optimization(initializer, download_result["path"])

    ros_enabled, isaacsim_ros_ws = _step6_ros_integration(
        initializer, global_dir_name,
        forced_value=ros_forced, forced_ws=ros_ws_forced,
        sim_version=resolved_version,
    )
    _step7_project_structure(initializer)
    linked = _step8_project_link(initializer, sim_version=resolved_version)
    if linked is None:
        # Everything below describes the linked install: the .vscode configs are
        # read from it and pow.toml records its version.  Writing either against
        # a link that is not there would leave the project inconsistent.
        console.print(
            Panel(
                "[bold red]✘ Initialization incomplete: Isaac Sim could not be linked."
                "[/bold red]",
                border_style="red",
            )
        )
        raise SystemExit(1)

    _step9_vscode_setup(
        initializer,
        version=resolved_version,
        version_changed=linked["status"] in ("Created", "Repointed"),
    )

    finalized = _step10_finalize(
        initializer, override_pow_toml or sim_version is not None, ros_enabled, isaacsim_ros_ws,
        sim_version=resolved_version,
    )

    if not finalized:
        console.print(
            Panel(
                "[bold red]✘ Initialization incomplete: pow.toml was not updated.[/bold red]",
                border_style="red",
            )
        )
        raise SystemExit(1)

    console.print(
        Panel(
            "[bold green]✨ Project initialized successfully! ✨[/bold green]",
            border_style="green",
        )
    )
