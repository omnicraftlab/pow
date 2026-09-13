"""Recovery tests never invoke Docker or mutate a real workspace."""
import json
from types import SimpleNamespace
from unittest.mock import Mock

import click
import pytest

from pow_cli.core.ros_manager import RosManager, ImageCompatibilityError
from pow_cli.cli.init import _step6_ros_integration


@pytest.fixture
def manager(mocker, tmp_path):
    cfg = Mock(ros_distro="jazzy")
    cfg.get.return_value = "6.1.0"
    mgr = RosManager(cfg)
    mocker.patch.object(mgr, "validate_workspace")
    mocker.patch.object(RosManager, "image_exists", return_value=True)
    return mgr


@pytest.mark.parametrize("label", [None, "6.0.1", "6.1.0"])
@pytest.mark.parametrize("accept", [True, False])
def test_image_recovery(manager, mocker, tmp_path, label, accept):
    run = mocker.patch("subprocess.run", return_value=SimpleNamespace(
        returncode=0, stdout=json.dumps([{"Config": {"Labels": {RosManager._SIM_LABEL: label}}}]), stderr=""))
    process = Mock(stdout=iter(["built\n"]), returncode=0)
    popen = mocker.patch("subprocess.Popen", return_value=process)
    confirm = Mock(return_value=accept)
    if label != "6.1.0" and not accept:
        with pytest.raises(ImageCompatibilityError):
            manager.build_simros_image(ws_path=tmp_path, sim_version="6.1.0", confirm_rebuild=confirm)
        popen.assert_not_called()
    else:
        result = manager.build_simros_image(ws_path=tmp_path, sim_version="6.1.0", confirm_rebuild=confirm)
        assert result["status"] == ("existed" if label == "6.1.0" else "built")
        if label == "6.1.0":
            popen.assert_not_called()
        else:
            cmd = popen.call_args.args[0]
            assert cmd[:2] == ["docker", "build"]
            assert cmd[cmd.index("-t") + 1] == "pow_simros_jazzy"
            assert cmd[cmd.index("--label") + 1] == f"{RosManager._SIM_LABEL}=6.1.0"
            assert cmd[cmd.index("--build-context") + 1] == f"ros_ws={tmp_path / 'jazzy_ws'}"
            assert "--no-cache" not in cmd
    assert confirm.call_count == (0 if label == "6.1.0" else 1)
    assert all(c.args[0][:3] == ["docker", "image", "inspect"] for c in run.call_args_list)


@pytest.mark.parametrize("returncode,output", [(1, ""), (0, "not json")])
def test_inspection_errors_do_not_prompt(manager, mocker, tmp_path, returncode, output):
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=returncode, stdout=output, stderr="daemon unavailable"))
    popen = mocker.patch("subprocess.Popen")
    confirm = Mock()
    with pytest.raises(click.ClickException, match="Could not inspect"):
        manager.build_simros_image(ws_path=tmp_path, confirm_rebuild=confirm)
    confirm.assert_not_called()
    popen.assert_not_called()


def test_existence_check_reports_daemon_error(mocker):
    mocker.patch("subprocess.run", return_value=SimpleNamespace(returncode=1, stdout="", stderr="permission denied"))
    with pytest.raises(click.ClickException, match="permission denied"):
        RosManager.image_exists("image")


@pytest.mark.parametrize("accept,build_fails", [(False, False), (True, True), (True, False)])
def test_init_prompt_and_failure_order(mocker, tmp_path, accept, build_fails):
    cfg = Mock(ros_distro="jazzy", ros_bridge="jazzy", ros_dockerfile="Dockerfile", ros_docker_image="custom")
    mgr = RosManager(cfg)
    mocker.patch("pow_cli.cli.init.RosManager", return_value=mgr)
    mocker.patch.object(mgr, "setup_ros_workspace", return_value={"ros_distro": "jazzy", "ubuntu_version": "24.04"})
    mocker.patch.object(mgr, "validate_workspace")
    mocker.patch.object(RosManager, "image_exists", return_value=True)
    mocker.patch.object(mgr, "validate_image", side_effect=ImageCompatibilityError("Run pow init and accept the rebuild prompt"))
    custom = mocker.patch.object(mgr, "build_custom_ros_image")
    confirm = mocker.patch("pow_cli.cli.init.Confirm.ask", return_value=accept)
    process = Mock(stdout=iter(["build diagnostic\n"]), returncode=1 if build_fails else 0)
    popen = mocker.patch("subprocess.Popen", return_value=process)
    initializer = Mock(config=cfg)
    if not accept or build_fails:
        with pytest.raises(SystemExit):
            _step6_ros_integration(initializer, ".pow", True, str(tmp_path), "6.1.0")
        custom.assert_not_called()
    else:
        assert _step6_ros_integration(initializer, ".pow", True, str(tmp_path), "6.1.0")[0]
        custom.assert_called_once()
    assert confirm.call_args.kwargs["default"] is False
    assert popen.call_count == int(accept)


# ── aarch64: the bundled image's base is amd64-only ─────────────────────────────

def test_image_builds_refuse_aarch64(manager, mocker, tmp_path):
    mocker.patch("platform.machine", return_value="aarch64")
    run = mocker.patch("subprocess.run")
    popen = mocker.patch("subprocess.Popen")

    with pytest.raises(click.ClickException, match="amd64-only; ROS Docker images are not available on aarch64"):
        manager.build_simros_image(ws_path=tmp_path, sim_version="6.1.0")
    with pytest.raises(click.ClickException, match="amd64-only"):
        manager.build_custom_ros_image(sim_version="6.1.0", ws_path=tmp_path)
    run.assert_not_called()
    popen.assert_not_called()


def test_pow_ros_refuses_aarch64_before_looking_for_the_image(mocker, tmp_path, monkeypatch, reset_config_singleton):
    (tmp_path / "pow.toml").write_text('[sim]\nversion = "6.1.0"\nenable_ros = true\n')
    monkeypatch.chdir(tmp_path)
    mocker.patch("platform.machine", return_value="aarch64")
    exists = mocker.patch.object(RosManager, "image_exists")

    with pytest.raises(click.ClickException, match="amd64-only"):
        RosManager._load_and_validate_config()
    exists.assert_not_called()


def test_init_skips_ros_image_build_on_aarch64(mocker, tmp_path, capsys):
    mocker.patch("platform.machine", return_value="aarch64")
    cfg = Mock(ros_distro="jazzy", ros_bridge="jazzy", ros_dockerfile="Dockerfile", ros_docker_image="custom")
    mgr = RosManager(cfg)
    mocker.patch("pow_cli.cli.init.RosManager", wraps=RosManager, return_value=mgr)
    setup = mocker.patch.object(mgr, "setup_ros_workspace", return_value={"ros_distro": "jazzy", "ubuntu_version": "24.04"})
    simros = mocker.patch.object(mgr, "build_simros_image")
    custom = mocker.patch.object(mgr, "build_custom_ros_image")

    enabled, ws = _step6_ros_integration(Mock(config=cfg), ".pow", True, str(tmp_path), "6.1.0")

    assert enabled is True
    assert ws == str(tmp_path)
    setup.assert_called_once()
    simros.assert_not_called()
    custom.assert_not_called()
    assert "Skipping ROS Docker image build" in capsys.readouterr().out
