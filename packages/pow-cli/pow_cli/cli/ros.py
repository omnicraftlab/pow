"""Ros command implementation."""

import click
from rich.panel import Panel
from ..common.utils import console
from ..core.ros_manager import RosManager


def _launch_container(extra_args, verbose: bool):
    """Launch or attach to the ROS container, rendering errors as panels."""
    try:
        RosManager.run_simros_container(extra_args=extra_args, verbose=verbose)
    except click.ClickException:
        raise
    except Exception as e:
        console.print(
            Panel(
                f"[bold red]✘[/bold red]  {e}",
                title="[bold red]ROS Error[/bold red]",
                border_style="red",
            )
        )
        raise SystemExit(1)


class RosGroup(click.Group):
    """Group that falls through to `launch` for unrecognized arguments."""

    def resolve_command(self, ctx, args):
        if args and self.get_command(ctx, args[0]) is not None:
            return super().resolve_command(ctx, args)
        launch = self.get_command(ctx, "launch")
        return launch.name, launch, args


@click.group(
    name="ros",
    cls=RosGroup,
    invoke_without_command=True,
    context_settings={"ignore_unknown_options": True},
)
@click.pass_context
def ros_group(ctx: click.Context):
    """Launch or manage the ROS docker container.

    Without a subcommand, launches an interactive session in the container
    running the image from `ros_docker_image` in pow.toml (or attaches to it
    if it is already running).  Unrecognized arguments are forwarded as the
    container command (default: /bin/bash), e.g. `pow ros ros2 topic list`.

    \b
    Subcommands:
      launch  Explicitly launch the container (same as bare `pow ros`).
      build   Build the custom image from `ros_dockerfile`.

    \b
    Requires:
      - ROS integration enabled in pow.toml (enable_ros = true).
      - The pow_simros Docker image built via `pow init`.
    """
    if ctx.invoked_subcommand is None:
        _launch_container(None, False)


@ros_group.command(
    name="launch",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option("--verbose", "-v", is_flag=True, default=False, help="Show detailed feedback during container launch.")
@click.pass_context
def launch_cmd(ctx: click.Context, verbose: bool):
    """Launch the ROS container, forwarding extra args as the container command."""
    _launch_container(ctx.args or None, verbose)


@ros_group.command(name="build")
@click.option("--no-cache", is_flag=True, default=False, help="Build without using the Docker layer cache.")
def build_cmd(no_cache: bool):
    """Build the custom ROS image from `ros_dockerfile` in pow.toml."""
    ros_mgr = RosManager()
    config = ros_mgr.config

    if config.project_root is None:
        raise click.ClickException("Not initialized. Run `pow init` first.")

    if not RosManager.docker_image_supported():
        raise click.ClickException(RosManager.docker_image_unsupported_message())

    if not config.ros_dockerfile:
        console.print(
            "[yellow]No `ros_dockerfile` set in pow.toml; nothing to build.[/yellow]\n"
            f"The bundled [bold]pow_simros_{config.ros_distro}[/bold] image is built by `pow init`."
        )
        return

    base_image = f"pow_simros_{config.ros_distro}"
    if not RosManager.image_exists(base_image):
        distro_ws = config.ros_ws_path / f"{config.ros_distro}_ws"
        if not distro_ws.exists():
            raise click.ClickException(
                f"Base image '{base_image}' not found and the ROS workspace "
                f"'{distro_ws}' does not exist.\n"
                "Run `pow init` first to set up the ROS workspace."
            )

        console.print(f"[yellow]Base image '{base_image}' not found — building it first.[/yellow]")

        def simros_status_callback(state):
            if state == "simros_building":
                base_status.update(f"[bold green]Building base image '{base_image}'...")
            elif state.startswith("simros_building:"):
                line = state[len("simros_building:"):]
                base_status.update(f"[bold green]{base_image} build:[/bold green] [dim]{line[:80]}[/dim]")

        with console.status(f"Building base image '{base_image}'...") as base_status:
            try:
                ros_mgr.build_simros_image(status_callback=simros_status_callback)
            except Exception as e:
                console.print(
                    Panel(
                        f"[bold red]✘[/bold red]  {e}",
                        title="[bold red]ROS Build Error[/bold red]",
                        border_style="red",
                    )
                )
                raise SystemExit(1)

        console.print(f"[green]✔[/green] Base Docker image [bold]{base_image}[/bold] built successfully.")

    custom_image = config.ros_docker_image

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
                no_cache=no_cache,
            )
        except Exception as e:
            console.print(
                Panel(
                    f"[bold red]✘[/bold red]  {e}",
                    title="[bold red]ROS Build Error[/bold red]",
                    border_style="red",
                )
            )
            raise SystemExit(1)

    console.print(
        f"[green]✔[/green] Custom Docker image [bold]{custom_image}[/bold] "
        f"built from [dim]{config.ros_dockerfile}[/dim]."
    )
