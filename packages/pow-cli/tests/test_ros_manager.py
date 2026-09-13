import re

import click
import pytest
from pathlib import Path
from unittest.mock import MagicMock

from pow_cli.core.ros_manager import RosManager


def _make_config(
    *,
    ros_dockerfile="",
    ros_docker_image="pow_simros",
    ros_distro="jazzy",
    project_root=Path("/home/user/myproject"),
):
    """Build a MagicMock PowConfig with the ROS-related attributes set."""
    cfg = MagicMock()
    cfg.ros_dockerfile = ros_dockerfile
    cfg.ros_docker_image = ros_docker_image
    cfg.ros_distro = ros_distro
    cfg.project_root = project_root
    cfg.ros_ws_path = Path("/home/user/IsaacSim-ros_workspaces")
    cfg.ros_image_name = (
        ros_docker_image if ros_dockerfile else f"pow_simros_{ros_distro}"
    )
    # Mirror PowConfig.ros_container_name: image name sanitized for docker.
    cfg.ros_container_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", cfg.ros_image_name)
    return cfg


# ── build_custom_ros_image ──────────────────────────────────────────────────────

def test_build_custom_ros_image_skips_when_unset():
    """No ros_dockerfile → build is skipped and docker is never invoked."""
    cfg = _make_config(ros_dockerfile="")
    mgr = RosManager(config=cfg)

    result = mgr.build_custom_ros_image()
    assert result == {"status": "skipped"}


def test_build_custom_ros_image_missing_dockerfile_raises(mocker):
    """A configured but missing Dockerfile raises a clear error."""
    cfg = _make_config(ros_dockerfile="docker/Dockerfile.simros")
    mgr = RosManager(config=cfg)
    mocker.patch("pathlib.Path.exists", return_value=False)

    with pytest.raises(RuntimeError, match="Custom ROS Dockerfile not found"):
        mgr.build_custom_ros_image()


def test_build_custom_ros_image_builds_with_docker_image_name(mocker):
    """A configured Dockerfile builds and tags the image with ros_docker_image."""
    cfg = _make_config(
        ros_dockerfile="docker/Dockerfile.simros",
        ros_docker_image="my_robot_sim",
    )
    mgr = RosManager(config=cfg)
    mocker.patch("pathlib.Path.exists", return_value=True)

    fake_proc = MagicMock()
    fake_proc.stdout = iter(["building...\n"])
    fake_proc.returncode = 0
    popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    result = mgr.build_custom_ros_image()

    assert result == {"status": "built", "image": "my_robot_sim"}
    build_cmd = popen.call_args[0][0]
    assert build_cmd[:3] == ["docker", "build", "-f"]
    assert "-t" in build_cmd
    assert build_cmd[build_cmd.index("-t") + 1] == "my_robot_sim"
    assert "--no-cache" not in build_cmd


def test_build_custom_ros_image_no_cache(mocker):
    """no_cache=True adds --no-cache to the docker build command."""
    cfg = _make_config(
        ros_dockerfile="docker/Dockerfile.simros",
        ros_docker_image="my_robot_sim",
    )
    mgr = RosManager(config=cfg)
    mocker.patch("pathlib.Path.exists", return_value=True)

    fake_proc = MagicMock()
    fake_proc.stdout = iter(["building...\n"])
    fake_proc.returncode = 0
    popen = mocker.patch("subprocess.Popen", return_value=fake_proc)

    mgr.build_custom_ros_image(no_cache=True)

    build_cmd = popen.call_args[0][0]
    assert "--no-cache" in build_cmd
    # The build context (project root) must remain the last argument.
    assert build_cmd[-1] == str(cfg.project_root)


def test_build_custom_ros_image_nonzero_exit_raises(mocker):
    """A non-zero docker build exit code raises RuntimeError."""
    cfg = _make_config(ros_dockerfile="docker/Dockerfile.simros")
    mgr = RosManager(config=cfg)
    mocker.patch("pathlib.Path.exists", return_value=True)

    fake_proc = MagicMock()
    fake_proc.stdout = iter(["oops\n"])
    fake_proc.returncode = 1
    mocker.patch("subprocess.Popen", return_value=fake_proc)

    with pytest.raises(RuntimeError, match="failed with exit code"):
        mgr.build_custom_ros_image()


# ── image_exists ────────────────────────────────────────────────────────────────

def test_image_exists_appends_latest_for_untagged_reference(mocker):
    """An untagged image reference is inspected as <image>:latest."""
    run = mocker.patch("subprocess.run", return_value=MagicMock(returncode=0))

    assert RosManager.image_exists("pow_simros_jazzy") is True
    assert run.call_args[0][0] == [
        "docker", "image", "inspect", "pow_simros_jazzy:latest"
    ]


def test_image_exists_keeps_explicit_tag(mocker):
    """A tagged reference is inspected as-is (no extra :latest appended)."""
    run = mocker.patch("subprocess.run", return_value=MagicMock(returncode=1, stderr="Error: No such image", stdout=""))

    assert RosManager.image_exists("ghcr.io/acme/robot:v1") is False
    assert run.call_args[0][0] == [
        "docker", "image", "inspect", "ghcr.io/acme/robot:v1"
    ]


# ── isaacsim_bridge_env ─────────────────────────────────────────────────────────

def _make_bridge_config(
    tmp_path, bridge_distro="humble", version="5.1.0", ext="isaacsim.ros2.bridge",
):
    """MagicMock PowConfig with an Isaac Sim install containing bridge libs."""
    cfg = MagicMock()
    cfg.global_path = tmp_path
    cfg.get_ros_bridge.return_value = bridge_distro
    cfg.get.return_value = version
    lib = tmp_path / "isaacsim" / version / "exts" / ext / bridge_distro / "lib"
    lib.mkdir(parents=True)
    return cfg, lib


def test_isaacsim_bridge_env_uses_config_bridge_distro(tmp_path, mocker):
    """The bridge distro is resolved from the config for the given profile."""
    cfg, _ = _make_bridge_config(tmp_path, bridge_distro="humble")
    mocker.patch.dict("os.environ", {}, clear=True)

    env = RosManager.isaacsim_bridge_env(cfg, profile="perf")

    cfg.get_ros_bridge.assert_called_once_with("perf")
    assert env["ROS_DISTRO"] == "humble"


def test_isaacsim_bridge_env_sets_bridge_variables(tmp_path, mocker):
    """ROS_DISTRO, RMW and the bridge lib path are set from the config."""
    cfg, lib = _make_bridge_config(tmp_path, bridge_distro="jazzy")
    mocker.patch.dict("os.environ", {}, clear=True)

    env = RosManager.isaacsim_bridge_env(cfg)

    assert env["ROS_DISTRO"] == "jazzy"
    # No host RMW set → fall back to Fast DDS.
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
    assert env["LD_LIBRARY_PATH"].split(":")[-1] == str(lib)


def test_isaacsim_bridge_env_inherits_host_rmw(tmp_path, mocker):
    """RMW_IMPLEMENTATION set on the host is preserved, not overwritten."""
    cfg, _ = _make_bridge_config(tmp_path, bridge_distro="jazzy")
    mocker.patch.dict(
        "os.environ", {"RMW_IMPLEMENTATION": "rmw_cyclonedds_cpp"}, clear=True
    )

    env = RosManager.isaacsim_bridge_env(cfg)

    assert env["RMW_IMPLEMENTATION"] == "rmw_cyclonedds_cpp"


def test_isaacsim_bridge_env_cleans_host_ros_environment(tmp_path, mocker):
    """Conflicting ROS vars are removed and /opt/ros paths stripped."""
    cfg, lib = _make_bridge_config(tmp_path, bridge_distro="humble")
    mocker.patch.dict(
        "os.environ",
        {
            "ROS_VERSION": "2",
            "ROS_PYTHON_VERSION": "3",
            "ROS_DISTRO": "iron",
            "AMENT_PREFIX_PATH": "/opt/ros/iron",
            "COLCON_PREFIX_PATH": "/opt/ros/iron",
            "PYTHONPATH": "/opt/ros/iron/lib/python3.10/site-packages",
            "CMAKE_PREFIX_PATH": "/opt/ros/iron",
            "LD_LIBRARY_PATH": "/opt/ros/iron/lib:/usr/local/lib",
        },
        clear=True,
    )

    env = RosManager.isaacsim_bridge_env(cfg)

    for var in (
        "ROS_VERSION", "ROS_PYTHON_VERSION", "AMENT_PREFIX_PATH",
        "COLCON_PREFIX_PATH", "PYTHONPATH", "CMAKE_PREFIX_PATH",
    ):
        assert var not in env
    assert env["ROS_DISTRO"] == "humble"
    assert env["LD_LIBRARY_PATH"] == f"/usr/local/lib:{lib}"


def test_isaacsim_bridge_env_missing_libs_raises(tmp_path, mocker):
    """A missing bridge lib directory raises a ClickException."""
    cfg = MagicMock()
    cfg.global_path = tmp_path
    cfg.get_ros_bridge.return_value = "humble"
    cfg.get.return_value = "5.1.0"
    mocker.patch.dict("os.environ", {}, clear=True)

    with pytest.raises(click.ClickException, match="ROS2 libs for 'humble' not found"):
        RosManager.isaacsim_bridge_env(cfg)


def test_bridge_env_takes_dir_and_distro_without_config(tmp_path, mocker):
    """`pow sim` builds the same env from an install dir, with no PowConfig."""
    isaacsim_dir = tmp_path / "isaacsim" / "5.1.0"
    lib = isaacsim_dir / "exts" / "isaacsim.ros2.bridge" / "jazzy" / "lib"
    lib.mkdir(parents=True)
    mocker.patch.dict("os.environ", {"LD_LIBRARY_PATH": "/opt/ros/jazzy/lib"}, clear=True)

    env = RosManager.bridge_env(isaacsim_dir, "jazzy")

    assert env["ROS_DISTRO"] == "jazzy"
    assert env["RMW_IMPLEMENTATION"] == "rmw_fastrtps_cpp"
    assert env["LD_LIBRARY_PATH"] == str(lib)


# ── container launching uses ros_container_name ─────────────────────────────────

def test_start_new_container_uses_container_name(mocker):
    """_start_new_container names the container after the derived container name."""
    mocker.patch.dict("os.environ", {}, clear=True)
    cfg = _make_config(
        ros_dockerfile="docker/Dockerfile.simros",
        ros_docker_image="my_robot_sim",
    )
    mocker.patch("os.getuid", return_value=1000)
    mocker.patch("os.getgid", return_value=1000)
    mocker.patch("os.path.exists", return_value=False)
    run = mocker.patch("subprocess.run")

    RosManager._start_new_container(cfg, "my_robot_sim")

    # The `docker rm -f <name>` cleanup call must target the configured name.
    rm_calls = [c for c in run.call_args_list if c[0][0][:3] == ["docker", "rm", "-f"]]
    assert rm_calls and rm_calls[0][0][0][3] == "my_robot_sim"

    # The `docker run ... --name <name>` call must use the configured name.
    run_calls = [
        c for c in run.call_args_list
        if c[0][0][:2] == ["docker", "run"] and "--name" in c[0][0]
    ]
    assert run_calls
    cmd = run_calls[0][0][0]
    assert cmd[cmd.index("--name") + 1] == "my_robot_sim"



# ── ROS 2 library location across Isaac Sim releases ────────────────────────────

def test_bridge_env_finds_ros2_core_ext(tmp_path, mocker):
    """Isaac Sim 6.0 renamed isaacsim.ros2.bridge to isaacsim.ros2.core."""
    isaacsim_dir = tmp_path / "isaacsim" / "6.1.0"
    lib = isaacsim_dir / "exts" / "isaacsim.ros2.core" / "jazzy" / "lib"
    lib.mkdir(parents=True)
    mocker.patch.dict("os.environ", {}, clear=True)

    env = RosManager.bridge_env(isaacsim_dir, "jazzy")

    assert env["LD_LIBRARY_PATH"] == str(lib)


def test_bridge_env_prefers_ros2_core_over_bridge(tmp_path, mocker):
    """When both exist the newer extension name wins."""
    isaacsim_dir = tmp_path / "isaacsim" / "6.1.0"
    core_lib = isaacsim_dir / "exts" / "isaacsim.ros2.core" / "jazzy" / "lib"
    bridge_lib = isaacsim_dir / "exts" / "isaacsim.ros2.bridge" / "jazzy" / "lib"
    core_lib.mkdir(parents=True)
    bridge_lib.mkdir(parents=True)
    mocker.patch.dict("os.environ", {}, clear=True)

    env = RosManager.bridge_env(isaacsim_dir, "jazzy")

    assert env["LD_LIBRARY_PATH"] == str(core_lib)


def test_isaacsim_bridge_env_reads_ros2_core_via_config(tmp_path, mocker):
    cfg, lib = _make_bridge_config(
        tmp_path, bridge_distro="jazzy", version="6.1.0", ext="isaacsim.ros2.core",
    )
    mocker.patch.dict("os.environ", {}, clear=True)

    env = RosManager.isaacsim_bridge_env(cfg)

    assert env["LD_LIBRARY_PATH"] == str(lib)


# ── workspace ref tracks the Isaac Sim version ──────────────────────────────────

@pytest.mark.parametrize(
    "version,expected_ref",
    [("5.1.0", "IsaacSim-5.1.0")],
)
def test_setup_ros_workspace_clones_matching_ref(tmp_path, mocker, version, expected_ref):
    cfg = MagicMock()
    cfg.ros_distro = "jazzy"
    cfg.ubuntu_version = "24.04"
    run = mocker.patch("pow_cli.core.ros_manager.subprocess.run")

    result = RosManager(config=cfg).setup_ros_workspace(
        ws_path=tmp_path / "ws", sim_version=version,
    )

    cmd = run.call_args[0][0]
    assert cmd[:4] == ["git", "clone", "-b", expected_ref]
    assert result["ws_ref"] == expected_ref


def test_setup_ros_workspace_rejects_unknown_version(tmp_path):
    cfg = MagicMock()
    cfg.ros_distro = "jazzy"
    cfg.ubuntu_version = "24.04"

    with pytest.raises(click.ClickException, match="Unsupported Isaac Sim version"):
        RosManager(config=cfg).setup_ros_workspace(
            ws_path=tmp_path / "ws", sim_version="9.9.9",
        )
